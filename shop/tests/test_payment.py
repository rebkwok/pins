from datetime import datetime, UTC

import pytest

from django.urls import reverse

from salesman.core.utils import get_salesman_model
from shop.payment import PayInAdvance, PayByStripe
from shop.tests.factories import STRIPE_ACCOUNT


Basket = get_salesman_model("Basket")

Order = get_salesman_model("Order")

pytestmark = pytest.mark.django_db


def test_pay_in_advance(rf, basket):
    basket_id = basket.id
    request = rf.post("/", {"name": "Test buyer"})
    payment = PayInAdvance()
    redirect_url = payment.basket_payment(basket, request)
    assert not Basket.objects.filter(id=basket.id).exists()

    new_order = Order.objects.get()
    assert redirect_url == request.build_absolute_uri(
        reverse("shop:new_order_status", args=(new_order.token,))
    )
    assert new_order.extra == {"basket_id": basket_id}
    assert new_order.status == "HOLD"


def basket_from_checkout(basket):
    # Add the extra fields that are added by the checkout serializer when
    # basket is progressed to payment
    basket.extra = {
        "basket_id": basket.id,
        "email": "test@test.com",
        "shipping_address": "-",
        "billing_address": "-",
        "payment_method": "stripe",
    }
    return basket


@pytest.fixture
def mock_stripe(requests_mock):
    yield requests_mock.post(
        "https://api.stripe.com/v1/checkout/sessions",
        json={
            "id": "test-session",
            "object": "checkout.session",
            "url": "https://stripe-session-url",
            # 2024-01-01 10:31 UTC
            "expires_at": 1704105060,
        },
    )


def stripe_session_data(**params):
    return {
        "id": "test-session",
        "object": "checkout.session",
        "customer_details": {"email": "test@test.com"},
        "amount_total": 2000,
        "status": "complete",
        "payment_status": "paid",
        "payment_intent": "payment-intent-id",
        "client_reference_id": "basket_1234",
        **params,
    }


def test_pay_by_stripe(mock_stripe, rf, basket, freezer):
    freezer.move_to("2024-01-01 10:00")
    basket = basket_from_checkout(basket)
    request = rf.post("/", {"name": "Test buyer"})
    payment = PayByStripe()
    redirect_url = payment.basket_payment(basket, request)
    assert redirect_url == "https://stripe-session-url"
    assert basket.extra["name"] == "Test buyer"
    # basket still exists - not deleted  and order not created until the webhook is completed
    assert Basket.objects.filter(id=basket.id).exists()
    # payment has started, so the basket is locked, and its items are held until
    # 5 mins after the session expires
    basket.refresh_from_db()
    assert basket.payment_in_progress
    assert basket.stripe_session_id == "test-session"
    assert basket.stripe_session_url == "https://stripe-session-url"
    assert basket.timeout == datetime(2024, 1, 1, 10, 36, tzinfo=UTC)
    # the session is created on the connected account, as a direct charge
    assert mock_stripe.last_request.headers["Stripe-Account"] == STRIPE_ACCOUNT
    assert "payment_intent_data" not in mock_stripe.last_request.text


def test_get_stripe_session_data(rf, basket, freezer):
    freezer.move_to("2024-01-01 10:00")
    basket = basket_from_checkout(basket)
    data = PayByStripe().get_session_data(basket, rf.post("/"))
    assert data["metadata"] == {"shipping_method": "collect"}
    # 31 mins from now
    assert data["expires_at"] == int(datetime(2024, 1, 1, 10, 31, tzinfo=UTC).timestamp())
    # the customer, found by their email (so Checkout can offer bank transfers)
    assert data["customer"] == "cus_test"


def test_get_stripe_session_data_delivery(rf, basket):
    basket = basket_from_checkout(basket)
    basket.shipping_method = "deliver"
    basket.update(request=None)
    data = PayByStripe().get_session_data(basket, rf.post("/"))
    assert data["metadata"] == {"shipping_method": "deliver"}
    # shipping is a line item
    assert [item["price_data"]["product_data"]["name"] for item in data["line_items"]] == [
        "Test Product - Small",
        "Shipping",
    ]
    assert data["line_items"][1]["price_data"]["unit_amount"] == 499


def test_stripe_session_expiry_follows_basket_timeout(rf, basket, freezer, settings):
    settings.BASKET_TIMEOUT_MINUTES = 45
    freezer.move_to("2024-01-01 10:00")
    basket = basket_from_checkout(basket)
    session_data = PayByStripe().get_session_data(basket, rf.post("/"))
    assert session_data["expires_at"] == int(
        datetime(2024, 1, 1, 10, 46, tzinfo=UTC).timestamp()
    )


def test_cancel_view(client):
    resp = client.get(reverse("stripe-connect-cancel"))
    assert "Your payment was cancelled" in resp.content.decode()
    assert reverse("shop:basket") in resp.content.decode()


def test_success_view(client, requests_mock, basket):
    basket = basket_from_checkout(basket)
    basket.save()
    session_mock = requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(client_reference_id=f"basket_{basket.id}"),
    )
    resp = client.get(reverse("stripe-connect-success") + "?session_id=test-session")
    content = resp.content.decode()

    # order is fulfilled without waiting for the webhook
    order = Order.objects.get()
    assert order.status == Order.Status.PROCESSING
    assert order.amount_paid == 20
    assert not Basket.objects.filter(id=basket.id).exists()

    assert f"Your order reference is <strong>{order.ref}</strong>" in content
    assert "You have been charged £20.00" in content
    assert "Your order confirmation has been emailed to test@test.com" in content
    assert reverse("shop:order_status", args=(order.token,)) in content
    # basket icon is hidden
    assert "fa-basket-shopping" not in content
    # only the session is retrieved from stripe
    assert session_mock.call_count == 1
    assert requests_mock.call_count == 1


def test_success_view_payment_pending(client, requests_mock, basket):
    # a payment that completes later (e.g. a bank debit): the order, awaiting
    # payment
    basket = basket_from_checkout(basket)
    basket.save()
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(client_reference_id=f"basket_{basket.id}", payment_status="unpaid"),
    )
    content = client.get(reverse("stripe-connect-success") + "?session_id=test-session").content.decode()
    order = Order.objects.get()
    assert order.status == Order.Status.HOLD
    assert "Order received" in content
    assert "Order confirmed" not in content
    assert (
        "Your order will be processed once your payment of £20.00 has been received. "
        "We'll email you when it has."
    ) in content
    assert "You have been charged" not in content


def test_success_view_unpaid_session(client, requests_mock, basket):
    # (not complete, e.g. the address visited before paying)
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(status="open", payment_status="unpaid"),
    )
    resp = client.get(reverse("stripe-connect-success") + "?session_id=test-session")
    content = resp.content.decode()
    assert not Order.objects.exists()
    assert "Your order is being processed" in content
    assert "confirmation email at test@test.com shortly" in content
    assert "fa-basket-shopping" not in content
