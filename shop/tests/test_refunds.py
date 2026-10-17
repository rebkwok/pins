"""
Refunds: full refunds from the orders admin, and the customer emails. Refunds
recorded by the webhook are tested in salesman_stripe_connect.
"""
import html
from decimal import Decimal
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import pytest
from model_bakery import baker

from django.conf import settings
from django.contrib.messages import get_messages
from django.core import mail
from django.urls import reverse

from salesman.core.utils import get_salesman_model

from ..payment import PayByStripe
from ..wagtail_hooks import OrderAdmin

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")

REFUNDS_URL = "https://api.stripe.com/v1/refunds"


@pytest.fixture
def paid_order(order):
    # order total is £20
    order.status = Order.Status.PROCESSING
    order.email = "customer@test.com"
    order.save()
    order.pay(amount=Decimal("20.00"), transaction_id="pi_1", payment_method="stripe")
    mail.outbox.clear()
    yield order


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    yield client


def refund_json(refund_id="re_1", amount=2000, status="succeeded"):
    return {
        "id": refund_id,
        "object": "refund",
        "amount": amount,
        "status": status,
        "payment_intent": "pi_1",
    }


def refunds_list(*refunds):
    return {"object": "list", "data": list(refunds), "has_more": False, "url": "/v1/refunds"}


def refund_url(order):
    return OrderAdmin().url_helper.get_action_url("refund", order.pk)


def messages_for(resp):
    # Wagtail admin messages are rendered as HTML
    return [html.unescape(str(m)).strip() for m in get_messages(resp.wsgi_request)]


# Refunding from the orders admin


def test_refund_page(admin_client, paid_order):
    resp = admin_client.get(refund_url(paid_order))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "<strong>£20.00</strong> will be refunded" in content
    assert "To refund only part of an order, use the Stripe dashboard." in content
    assert "Refunding doesn't change stock." in content
    assert "2 x Test Product - Small" in content
    assert 'value="Yes, refund this order"' in content


def test_refund_order(admin_client, paid_order, requests_mock, django_capture_on_commit_callbacks):
    stripe_refund = requests_mock.post(REFUNDS_URL, json=refund_json())
    with django_capture_on_commit_callbacks(execute=True):
        resp = admin_client.post(refund_url(paid_order))

    assert resp.status_code == 302
    # refunded on the connected account
    assert stripe_refund.last_request.headers["Stripe-Account"] == "acct_dummy"
    assert parse_qs(stripe_refund.last_request.text) == {
        "payment_intent": ["pi_1"],
        "metadata[order]": [paid_order.ref],
    }
    paid_order.refresh_from_db()
    assert paid_order.status == Order.Status.REFUNDED
    assert paid_order.amount_refunded == Decimal("20.00")
    assert paid_order.amount_paid == 0
    refund_payment = paid_order.payments.get(transaction_id="re_1")
    assert refund_payment.amount == Decimal("-20.00")
    assert [note.message for note in paid_order.notes.all()] == ["Refund re_1 of £20.00"]
    assert messages_for(resp) == [
        f"£20.00 refunded for order {paid_order}. Stock hasn't been changed; update "
        "it manually if items are going back into stock."
    ]
    # the customer is emailed
    (email,) = mail.outbox
    assert email.to == ["customer@test.com"]
    assert email.subject == f"Order '{paid_order.ref}' has been refunded"
    assert (
        "We have refunded £20.00 to the card (or other payment method) you used for "
        "this order. It can take 5-10 working days to appear on your statement."
    ) in email.body


def test_refund_order_after_partial_refund(admin_client, paid_order, requests_mock):
    # £5 was refunded in Stripe; the rest is refunded from the admin
    PayByStripe.record_refund(paid_order, "re_partial", Decimal("5.00"))
    content = admin_client.get(refund_url(paid_order)).content.decode()
    assert "<strong>£15.00</strong> will be refunded" in content
    assert "less\n        £5.00 already refunded" in content

    requests_mock.post(REFUNDS_URL, json=refund_json(amount=1500))
    admin_client.post(refund_url(paid_order))
    paid_order.refresh_from_db()
    assert paid_order.status == Order.Status.REFUNDED
    assert paid_order.amount_refunded == Decimal("20.00")


def test_refund_already_refunded_order(admin_client, paid_order, requests_mock):
    paid_order.status = Order.Status.REFUNDED
    paid_order.save()
    assert "has already been refunded" in admin_client.get(refund_url(paid_order)).content.decode()
    resp = admin_client.post(refund_url(paid_order))
    assert messages_for(resp) == [f"Order {paid_order} has already been refunded."]
    assert not requests_mock.called


def test_refund_order_stripe_error(admin_client, paid_order, requests_mock):
    requests_mock.post(
        REFUNDS_URL,
        status_code=400,
        json={"error": {"message": "Charge pi_1 has already been refunded."}},
    )
    resp = admin_client.post(refund_url(paid_order))
    assert messages_for(resp) == [
        f"Error refunding order {paid_order}: pi_1: Charge pi_1 has already been refunded."
    ]
    paid_order.refresh_from_db()
    assert paid_order.status == Order.Status.PROCESSING
    assert paid_order.amount_refunded == 0


def test_refund_order_no_stripe_payments(admin_client, order, requests_mock):
    assert "has no Stripe payments to refund" in admin_client.get(refund_url(order)).content.decode()
    resp = admin_client.post(refund_url(order))
    assert messages_for(resp) == [f"Order {order} has no Stripe payments to refund."]
    assert not requests_mock.called


# Refunds recorded from the webhook (e.g. made in the Stripe dashboard)


def post_charge_refunded(client):
    event = Mock(
        type="charge.refunded",
        account=settings.SALESMAN_STRIPE_CONNECT_ACCOUNT,
        data=Mock(object=Mock(payment_intent="pi_1")),
    )
    with patch("salesman_stripe_connect.payment.stripe.Webhook") as mock_webhook:
        mock_webhook.construct_event.return_value = event
        return client.post(
            reverse("stripe-connect-webhook"), data={}, headers={"Stripe-Signature": "t=1"}
        )


def test_webhook_partial_refund_email(
    client, paid_order, requests_mock, django_capture_on_commit_callbacks
):
    requests_mock.get(REFUNDS_URL, json=refunds_list(refund_json(amount=500)))
    with django_capture_on_commit_callbacks(execute=True):
        resp = post_charge_refunded(client)
    assert resp.content.decode() == "1 refund(s) recorded"
    paid_order.refresh_from_db()
    assert paid_order.status == Order.Status.PROCESSING
    (email,) = mail.outbox
    assert email.subject == f"Order '{paid_order.ref}' has been partially refunded"
    assert "We have refunded £5.00 to the card (or other payment method)" in email.body


def test_webhook_refund_emailed_once(
    client, paid_order, requests_mock, django_capture_on_commit_callbacks
):
    # e.g. a refund from the orders admin, which the webhook then receives
    requests_mock.get(REFUNDS_URL, json=refunds_list(refund_json(amount=500)))
    with django_capture_on_commit_callbacks(execute=True):
        post_charge_refunded(client)
        post_charge_refunded(client)
    assert len(mail.outbox) == 1


# Order status page


def test_order_status_page_refunds(client, paid_order):
    PayByStripe.record_refund(paid_order, "re_1", Decimal("5.00"))
    content = client.get(reverse("shop:order_status", args=(paid_order.token,))).content.decode()
    assert "Amount paid: £20.00" in content
    assert "Amount refunded: £5.00" in content
    # nothing is due because of a refund
    assert "Amount outstanding" not in content
