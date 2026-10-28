"""
Payments that complete later (e.g. bank debits; salesman_stripe_connect creates
the order on hold, then pays or fails it): the shop's emails, stock and
discount codes
"""

import html
from unittest.mock import Mock

import pytest
from django.core import mail
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from ..models import DiscountCode, ShopSettings
from ..payment import PayByStripe
from ..status import OrderStatus
from .test_shipping import dispatcher, make_dispatcher, notified_dispatcher, shop_variants  # noqa: F401

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")


def session(basket, payment_status="unpaid", session_id="test-session", **params):
    return Mock(
        id=session_id,
        client_reference_id=f"basket_{basket.id}",
        status="complete",
        payment_status=payment_status,
        payment_intent="pi_1",
        **params,
    )


@pytest.fixture
def notify_settings():
    baker.make(ShopSettings, notify_email_addresses="shop@test.com")


def held_order(variants, django_capture_on_commit_callbacks, code=None, session_id="test-session"):
    basket = baker.make(
        Basket,
        shipping_method="deliver",
        extra={"email": "c@test.com", "name": "Cat", "shipping_address": "1 Road\nTown"},
    )
    for variant in variants:
        basket.add(variant, quantity=2)
    if code:
        basket.set_discount_code(code)
    basket.update(request=None)
    stripe_session = session(basket, session_id=session_id, amount_total=int(basket.total * 100))
    with django_capture_on_commit_callbacks(execute=True):
        order, message = PayByStripe.fulfil_session(None, stripe_session)
    assert message == "Order awaiting payment"
    return order, stripe_session


def emails_to(address):
    return [email for email in mail.outbox if email.to == [address]]


def test_held_then_paid(shop_variants, notified_dispatcher, notify_settings, django_capture_on_commit_callbacks):
    mug, card, raffle = shop_variants
    order, stripe_session = held_order([mug, card], django_capture_on_commit_callbacks)
    assert order.status == OrderStatus.HOLD
    # awaiting payment: the customer and shop are told, the dispatcher isn't yet
    (customer,) = emails_to("c@test.com")
    assert "It will be processed once payment has been received." in customer.body
    assert "(awaiting payment)" in emails_to("shop@test.com")[0].body
    assert not emails_to("ann@test.com")
    # the money arrives: paid, and the usual emails
    mail.outbox.clear()
    stripe_session.payment_status = "paid"
    with django_capture_on_commit_callbacks(execute=True):
        assert PayByStripe.fulfil_session(None, stripe_session) == (order, "Order paid")
    order.refresh_from_db()
    assert order.status == OrderStatus.PROCESSING
    assert order.is_paid
    (customer,) = emails_to("c@test.com")
    assert customer.subject == f"PINS shop order {order.ref} is being processed"
    assert emails_to("ann@test.com")


def test_held_then_paid_nothing_to_send(shop_variants, django_capture_on_commit_callbacks):
    # (e.g. raffle tickets): complete once paid
    mug, card, raffle = shop_variants
    order, stripe_session = held_order([raffle], django_capture_on_commit_callbacks)
    mail.outbox.clear()
    stripe_session.payment_status = "paid"
    with django_capture_on_commit_callbacks(execute=True):
        PayByStripe.fulfil_session(None, stripe_session)
    order.refresh_from_db()
    assert order.status == OrderStatus.COMPLETED
    (customer,) = emails_to("c@test.com")
    assert customer.subject == f"PINS shop order {order.ref} is complete"


def test_held_then_failed(shop_variants, notify_settings, django_capture_on_commit_callbacks):
    # the payment fails: stock and the discount code back, and emails
    mug, card, raffle = shop_variants
    code = baker.make(DiscountCode, code="PINS5OFF", amount=5)
    mug.refresh_from_db()
    mug_stock = mug.stock
    order, stripe_session = held_order([mug], django_capture_on_commit_callbacks, code=code)
    mug.refresh_from_db()
    assert mug.stock == mug_stock - 2
    code.refresh_from_db()
    assert code.order == order
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        assert PayByStripe.fail_session(stripe_session) == (order, "Payment failed")
    order.refresh_from_db()
    assert order.status == OrderStatus.FAILED
    assert order.display_status == "Payment failed"
    mug.refresh_from_db()
    assert mug.stock == mug_stock
    code.refresh_from_db()
    assert (code.order, code.date_used) == (None, None)
    (customer,) = emails_to("c@test.com")
    assert customer.subject == f"PINS shop order {order.ref}: payment failed"
    assert customer.body.startswith(
        f"The payment for order {order.ref} didn't go through, so the order has been "
        "cancelled and nothing will be sent. You're welcome to order again."
    )
    assert "\n--\n" in customer.body
    (shop,) = emails_to("shop@test.com")
    assert shop.subject == f"PINS shop order {order.ref}: payment failed"
    assert (
        "failed, so the order hasn't been paid: don't send anything. Its items have been "
        "put back in stock, and its discount code (PINS5OFF) can be used again. The "
        "customer has been emailed."
    ) in shop.body
    assert "--" not in shop.body


def test_failed_no_notify_addresses(shop_variants, django_capture_on_commit_callbacks):
    # just the customer; no discount code
    mug, card, raffle = shop_variants
    order, stripe_session = held_order([mug], django_capture_on_commit_callbacks)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        PayByStripe.fail_session(stripe_session)
    assert [email.to for email in mail.outbox] == [["c@test.com"]]


def test_failed_order_page(client, shop_variants, django_capture_on_commit_callbacks):
    mug, card, raffle = shop_variants
    order, stripe_session = held_order([mug], django_capture_on_commit_callbacks)
    PayByStripe.fail_session(stripe_session)
    client.force_login(baker.make("auth.User", is_superuser=True))
    content = html.unescape(client.get(reverse("shop_orders:edit", args=(order.pk,))).content.decode())
    assert "The order's payment failed, so its items can't be marked shipped." in content
    assert "Not sent" in content


# Orders still awaiting payment after 7 days (e.g. bank transfers never made)


def test_cancel_unpaid_orders(shop_variants, notify_settings, django_capture_on_commit_callbacks, requests_mock):
    from datetime import timedelta
    from io import StringIO

    from django.core.management import call_command
    from django.utils import timezone

    mug, card, raffle = shop_variants
    mug.refresh_from_db()
    stock = mug.stock
    order, _ = held_order([mug], django_capture_on_commit_callbacks)
    newer, _ = held_order([mug], django_capture_on_commit_callbacks, session_id="newer-session")
    Order.objects.filter(pk=order.pk).update(date_created=timezone.now() - timedelta(days=8))
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json={"id": "test-session", "object": "checkout.session", "payment_status": "unpaid", "payment_intent": "pi_1"},
    )
    requests_mock.get(
        "https://api.stripe.com/v1/payment_intents/pi_1",
        json={"id": "pi_1", "object": "payment_intent", "status": "requires_action", "amount_received": 0},
    )
    requests_mock.post("https://api.stripe.com/v1/payment_intents/pi_1/cancel", json={"id": "pi_1"})
    mail.outbox.clear()
    out = StringIO()
    with django_capture_on_commit_callbacks(execute=True):
        call_command("cancel_unpaid_orders", stdout=out)
    assert out.getvalue() == f"Order {order.ref}: Cancelled\nChecked 1 unpaid order(s)\n"
    order.refresh_from_db()
    assert order.status == OrderStatus.FAILED
    newer.refresh_from_db()
    assert newer.status == OrderStatus.HOLD
    # the cancelled order's stock is back (the newer one's still held), and
    # the customer and shop are emailed
    mug.refresh_from_db()
    assert mug.stock == stock - 2
    assert {tuple(email.to) for email in mail.outbox} == {("c@test.com",), ("shop@test.com",)}
