"""
Tests for the basket while a Stripe payment is in progress: holding and
locking the basket, the checkout.session.expired webhook, and checking or
cancelling the payment when the customer returns to their basket.
"""
from datetime import datetime, timedelta, UTC
from unittest.mock import Mock, patch

import pytest

from django.contrib.messages import get_messages
from django.urls import reverse

from salesman.basket.models import BASKET_ID_SESSION_KEY
from salesman.checkout.payment import PaymentError
from salesman.core.utils import get_salesman_model

from ..payment import PayByStripe
from .factories import STRIPE_ACCOUNT

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")

SESSION_URL = "https://api.stripe.com/v1/checkout/sessions/test-session"


@pytest.fixture
def paying_basket(basket, freezer):
    # Basket has 2 items; 3 left in stock. Payment started at 10:00; the
    # session expires at 10:31, and items are held until 10:36
    freezer.move_to("2024-01-01 10:00")
    basket.extra.update(
        {
            "email": "test@test.com",
            "shipping_address": "-",
            "billing_address": "-",
            "payment_method": "stripe",
        }
    )
    basket.start_payment(
        "test-session",
        "https://stripe-session-url",
        hold_until=datetime(2024, 1, 1, 10, 36, tzinfo=UTC),
    )
    yield basket


@pytest.fixture
def basket_client(client, paying_basket):
    session = client.session
    session[BASKET_ID_SESSION_KEY] = paying_basket.id
    session.save()
    yield client


def session_data(basket, **params):
    return {
        "id": "test-session",
        "object": "checkout.session",
        "client_reference_id": f"basket_{basket.id}",
        "customer_details": {"email": "test@test.com"},
        "amount_total": 2000,
        "status": "open",
        "payment_status": "unpaid",
        "payment_intent": "payment-intent-id",
        **params,
    }


def expired_session(basket, session_id="test-session"):
    return Mock(id=session_id, client_reference_id=f"basket_{basket.id}")


# Holding the basket


def test_reset_timeout_does_not_shorten_payment_hold(paying_basket, freezer):
    freezer.move_to("2024-01-01 10:05")
    # update() is called whenever the basket is displayed
    paying_basket.update(request=None)
    assert paying_basket.timeout == datetime(2024, 1, 1, 10, 36, tzinfo=UTC)

    paying_basket.end_payment()
    paying_basket.reset_timeout()
    assert paying_basket.timeout == datetime(2024, 1, 1, 10, 35, tzinfo=UTC)


def test_clear_expired_waits_for_payment_hold(paying_basket, freezer):
    # basket timeout would normally have passed, but the session hasn't expired
    freezer.move_to("2024-01-01 10:32")
    assert Basket.clear_expired() == 0
    assert paying_basket.items.exists()

    # fallback if the expired webhook doesn't arrive
    freezer.move_to("2024-01-01 10:37")
    assert Basket.clear_expired() == 1
    paying_basket.refresh_from_db()
    assert not paying_basket.items.exists()
    assert not paying_basket.payment_in_progress


def test_basket_payment_already_in_progress(rf, paying_basket):
    with pytest.raises(PaymentError):
        PayByStripe().basket_payment(paying_basket, rf.post("/"))


# checkout.session.expired webhook


def test_expire_basket_payment(paying_basket):
    variant = paying_basket.items.first().product
    basket, message = PayByStripe.expire_basket_payment(expired_session(paying_basket))
    assert message == "Payment expired"
    paying_basket.refresh_from_db()
    assert not paying_basket.items.exists()
    assert not paying_basket.payment_in_progress
    assert paying_basket.timeout is None
    variant.refresh_from_db()
    assert variant.stock == 5


def test_expire_basket_payment_other_session(paying_basket):
    # e.g. a session that was cancelled before a new one was started
    _, message = PayByStripe.expire_basket_payment(
        expired_session(paying_basket, session_id="other-session")
    )
    assert message == "Event ignored"
    assert paying_basket.items.exists()
    paying_basket.refresh_from_db()
    assert paying_basket.payment_in_progress


@pytest.mark.parametrize("reference", ["basket_1234", "order_1"])
def test_expire_basket_payment_ignored(reference):
    session = Mock(id="test-session", client_reference_id=reference)
    _, message = PayByStripe.expire_basket_payment(session)
    assert message == "Event ignored"


def test_webhook_session_expired(client, paying_basket):
    event = Mock(
        type="checkout.session.expired",
        account=STRIPE_ACCOUNT,
        data=Mock(object=expired_session(paying_basket)),
    )
    with patch("salesman_stripe_connect.payment.stripe.Webhook") as mock_webhook:
        mock_webhook.construct_event.return_value = event
        resp = client.post(
            reverse("stripe-connect-webhook"), data={}, headers={"Stripe-Signature": "t=1"}
        )
    assert resp.status_code == 200
    assert resp.content.decode() == "Payment expired"
    # the basket's items are returned to stock
    assert not paying_basket.items.exists()


# Basket locked during payment


def test_add_to_basket_locked(basket_client, paying_basket, product):
    variant = paying_basket.items.first().product
    resp = basket_client.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "product_id": variant.id,
            "product_type": "shop.ProductVariant",
            "quantity": 1,
        },
    )
    assert "can't be changed while a payment is in progress" in resp.content.decode()
    assert Basket.objects.get(id=paying_basket.id).quantity == 2


def test_update_quantity_locked(basket_client, paying_basket):
    item = paying_basket.items.first()
    resp = basket_client.post(
        reverse("shop:update_quantity", args=(item.ref,)),
        {"product_id": item.product.id, "quantity": 1},
    )
    assert "can't be changed while a payment is in progress" in resp.content.decode()
    assert Basket.objects.get(id=paying_basket.id).quantity == 2


def test_delete_basket_item_locked(basket_client, paying_basket):
    item = paying_basket.items.first()
    resp = basket_client.post(
        reverse("shop:delete_basket_item", args=(item.ref,)),
        {"product_id": item.product.id},
    )
    assert "can't be changed while a payment is in progress" in resp.content.decode()
    assert paying_basket.items.exists()


def test_checkout_locked(basket_client):
    resp = basket_client.get(
        reverse("shop:checkout") + "?payment-method=stripe&shipping-method=collect"
    )
    assert resp.status_code == 302
    assert resp.url == reverse("shop:basket")


# Returning to the basket during payment


def test_basket_view_payment_open(basket_client, paying_basket, requests_mock):
    requests_mock.get(SESSION_URL, json=session_data(paying_basket))
    resp = basket_client.get(reverse("shop:basket"))
    assert resp.templates[0].name == "shop/basket_payment_in_progress.html"
    content = resp.content.decode()
    assert "Payment in progress" in content
    assert 'href="https://stripe-session-url"' in content
    assert reverse("shop:cancel_payment") in content
    assert "Cancel payment and return to basket" in content


def test_basket_view_payment_completed(basket_client, paying_basket, requests_mock):
    # The customer paid, but didn't return to the success page and the webhook
    # hasn't arrived yet
    requests_mock.get(
        SESSION_URL,
        json=session_data(paying_basket, status="complete", payment_status="paid"),
    )
    resp = basket_client.get(reverse("shop:basket"))
    order = Order.objects.get()
    assert resp.status_code == 302
    assert resp.url == reverse("shop:new_order_status", args=(order.token,))
    assert order.amount_paid == 20
    assert not Basket.objects.filter(id=paying_basket.id).exists()


def test_basket_view_payment_expired(basket_client, paying_basket, requests_mock):
    requests_mock.get(SESSION_URL, json=session_data(paying_basket, status="expired"))
    resp = basket_client.get(reverse("shop:basket"))
    assert resp.templates[0].name == "shop/basket.html"
    assert "Basket is empty" in resp.content.decode()
    paying_basket.refresh_from_db()
    assert not paying_basket.payment_in_progress


def test_basket_view_stripe_error(basket_client, paying_basket, requests_mock):
    requests_mock.get(SESSION_URL, status_code=500, json={"error": {"message": "Error"}})
    resp = basket_client.get(reverse("shop:basket"))
    assert resp.templates[0].name == "shop/basket_payment_in_progress.html"


# Cancelling the payment


def test_cancel_payment(basket_client, paying_basket, requests_mock, freezer):
    freezer.move_to("2024-01-01 10:10")
    expire_mock = requests_mock.post(
        SESSION_URL + "/expire", json=session_data(paying_basket, status="expired")
    )
    resp = basket_client.post(reverse("shop:cancel_payment"))
    assert resp.status_code == 302
    assert resp.url == reverse("shop:basket")
    assert expire_mock.called

    # basket is unlocked, and keeps its items with a new timeout
    paying_basket.refresh_from_db()
    assert not paying_basket.payment_in_progress
    assert paying_basket.items.count() == 1
    assert paying_basket.timeout == datetime(2024, 1, 1, 10, 40, tzinfo=UTC)
    assert [str(m) for m in get_messages(resp.wsgi_request)] == ["Payment cancelled."]

    # the expired webhook for the cancelled session is then ignored
    _, message = PayByStripe.expire_basket_payment(expired_session(paying_basket))
    assert message == "Event ignored"
    assert paying_basket.items.exists()


def test_cancel_payment_already_completed(basket_client, paying_basket, requests_mock):
    requests_mock.post(
        SESSION_URL + "/expire",
        status_code=400,
        json={"error": {"message": "Only open sessions can be expired"}},
    )
    requests_mock.get(
        SESSION_URL,
        json=session_data(paying_basket, status="complete", payment_status="paid"),
    )
    resp = basket_client.post(reverse("shop:cancel_payment"))
    # redirects to the basket, which fulfils the order
    assert resp.url == reverse("shop:basket")
    paying_basket.refresh_from_db()
    assert paying_basket.payment_in_progress
    assert list(get_messages(resp.wsgi_request)) == []


def test_cancel_payment_stripe_error(basket_client, paying_basket, requests_mock):
    requests_mock.post(SESSION_URL + "/expire", status_code=500, json={"error": {}})
    resp = basket_client.post(reverse("shop:cancel_payment"))
    assert resp.url == reverse("shop:basket")
    paying_basket.refresh_from_db()
    assert paying_basket.payment_in_progress
    assert "couldn't be cancelled" in str(list(get_messages(resp.wsgi_request))[0])


def test_cancel_payment_get_not_allowed(basket_client):
    resp = basket_client.get(reverse("shop:cancel_payment"))
    assert resp.status_code == 405


def test_stripe_cancel_view_unlocks_basket(basket_client, paying_basket, requests_mock):
    requests_mock.post(
        SESSION_URL + "/expire", json=session_data(paying_basket, status="expired")
    )
    resp = basket_client.get(reverse("stripe-connect-cancel"))
    assert "Your payment was cancelled" in resp.content.decode()
    assert reverse("shop:basket") in resp.content.decode()
    paying_basket.refresh_from_db()
    assert not paying_basket.payment_in_progress
    assert paying_basket.items.exists()


def test_cancel_basket_payment_not_in_progress(basket, requests_mock):
    # e.g. the payment was cancelled in another tab; nothing to do
    assert PayByStripe.cancel_basket_payment(basket) is True
    assert not requests_mock.called


def test_stripe_cancel_view_stripe_error(
    basket_client, paying_basket, requests_mock, caplog
):
    requests_mock.post(SESSION_URL + "/expire", status_code=500, json={"error": {}})
    resp = basket_client.get(reverse("stripe-connect-cancel"))
    assert "Your payment was cancelled" in resp.content.decode()
    assert "Error cancelling Stripe session test-session" in caplog.text
    paying_basket.refresh_from_db()
    assert paying_basket.payment_in_progress

