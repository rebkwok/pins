from smtplib import SMTPException
from unittest.mock import patch

import pytest
from model_bakery import baker

from django.conf import settings
from django.core import mail

from salesman.core.utils import get_salesman_model
from salesman_stripe_connect import signals as stripe_signals

from ..models import ProductVariant


Order = get_salesman_model("Order")

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop_settings():
    baker.make(
        "shop.ShopSettings",
        notify_email_addresses="admin@test.com, another_admin@test.com",
        reply_to="shop@test.com",
    )


def checkout_basket(basket, payment_method):
    # Add the extra fields that are added by the checkout serializer when
    # basket is progressed to payment
    basket.extra = {
        "basket_id": basket.id,
        "email": "test@test.com",
        "shipping_address": "-",
        "billing_address": "-",
        "payment_method": payment_method,
    }
    return basket


def test_delete_basket_item_updates_stock(basket):
    # item product variant has 5 in stock initially
    # basket items contains 2, reduces stock to 3
    basket_item = basket.items.first()
    variant = basket_item.product
    assert variant.stock == 3
    # deleting the basket item puts the quanity back in stock
    basket_item.delete()
    assert variant.stock == 5


def test_basket_item_save_twice_does_not_double_count_stock(basket):
    # 5 in stock initially, 2 in basket
    basket_item = basket.items.first()
    variant = basket_item.product
    basket_item.quantity = 3
    basket_item.save()
    variant.refresh_from_db()
    assert variant.stock == 2
    # saving again with no change doesn't change stock
    basket_item.save()
    variant.refresh_from_db()
    assert variant.stock == 2


def test_concurrent_basket_stock_updates(product):
    # Two baskets holding separately loaded (stale) copies of the same variant
    # must not overwrite each other's stock changes
    variant = baker.make("shop.ProductVariant", product=product, price=10, stock=5)
    variant_1 = ProductVariant.objects.get(id=variant.id)
    variant_2 = ProductVariant.objects.get(id=variant.id)
    basket_1 = baker.make("shop.Basket")
    basket_2 = baker.make("shop.Basket")

    basket_1.add(variant_1, quantity=2)
    basket_2.add(variant_2, quantity=1)

    variant.refresh_from_db()
    assert variant.stock == 2


def test_delete_basket_after_order_keeps_order_items_out_of_stock(basket):
    # 5 in stock initially, 2 in basket
    variant = basket.items.first().product
    Order.objects.create_from_basket(basket, request=None)
    basket.delete()
    variant.refresh_from_db()
    assert variant.stock == 3


@pytest.mark.parametrize(
    "payment_status,body_text",
    [
        (
            Order.Status.HOLD,
            "Thank you for your order! It will be processed once payment has been received.",
        ),
        (
            Order.Status.PROCESSING,
            "Thank you for your order! It's being processed, and we'll email you when the items are sent.",
        ),
    ],
)
def test_emails_on_order_creation_no_shop_email_setting(
    django_capture_on_commit_callbacks, payment_status, body_text
):
    with django_capture_on_commit_callbacks(execute=True):
        new_order = baker.make(Order, status=payment_status, email="test@test.com")
    # email to customer only
    assert len(mail.outbox) == 1
    customer_email = mail.outbox[0]
    assert customer_email.to == ["test@test.com"]
    assert customer_email.reply_to == [settings.DEFAULT_FROM_EMAIL]
    assert customer_email.subject == f"PINS shop order {new_order.ref} has been received"
    assert body_text in customer_email.body


@pytest.mark.parametrize(
    "payment_status,body_text",
    [
        (
            Order.Status.HOLD,
            "Thank you for your order! It will be processed once payment has been received.",
        ),
        (
            Order.Status.PROCESSING,
            "Thank you for your order! It's being processed, and we'll email you when the items are sent.",
        ),
    ],
)
def test_emails_on_order_creation_with_shop_email_setting(
    django_capture_on_commit_callbacks, payment_status, body_text, shop_settings
):
    with django_capture_on_commit_callbacks(execute=True):
        new_order = baker.make(Order, status=payment_status, email="test@test.com")
    assert len(mail.outbox) == 2
    customer_email = mail.outbox[0]
    assert customer_email.to == ["test@test.com"]
    assert customer_email.reply_to == ["shop@test.com"]
    assert customer_email.subject == f"PINS shop order {new_order.ref} has been received"

    admin_email = mail.outbox[1]
    assert admin_email.to == ["admin@test.com", "another_admin@test.com"]
    assert admin_email.reply_to == ["shop@test.com"]
    assert admin_email.subject == f"PINS shop order {new_order.ref}: new order"
    assert admin_email.body.startswith(f"A new shop order {new_order.ref} has been received")


@pytest.mark.parametrize(
    "payment_status,new_payment_status,email_sent,subject",
    [
        (Order.Status.HOLD, Order.Status.HOLD, False, None),
        (Order.Status.HOLD, Order.Status.PROCESSING, True, "is being processed"),
        (Order.Status.HOLD, Order.Status.COMPLETED, True, "is complete"),
        (Order.Status.PROCESSING, Order.Status.COMPLETED, True, "is complete"),
    ],
)
def test_emails_on_order_status_change(
    django_capture_on_commit_callbacks,
    payment_status,
    new_payment_status,
    email_sent,
    subject,
):
    assert len(mail.outbox) == 0
    with django_capture_on_commit_callbacks(execute=True):
        new_order = baker.make(Order, status=payment_status, email="test@test.com")
    # email to customer only
    assert len(mail.outbox) == 1

    with django_capture_on_commit_callbacks(execute=True):
        new_order.status = new_payment_status
        new_order.save()
    if email_sent:
        assert len(mail.outbox) == 2
        assert mail.outbox[1].to == ["test@test.com"]
        assert mail.outbox[1].reply_to == [settings.DEFAULT_FROM_EMAIL]
        assert mail.outbox[1].subject == f"PINS shop order {new_order.ref} {subject}"
    else:
        assert len(mail.outbox) == 1


@pytest.mark.parametrize(
    "payment_status,new_payment_status,email_sent,subject",
    [
        (Order.Status.HOLD, Order.Status.HOLD, False, None),
        (Order.Status.HOLD, Order.Status.PROCESSING, True, "is being processed"),
        (Order.Status.HOLD, Order.Status.COMPLETED, True, "is complete"),
        (Order.Status.PROCESSING, Order.Status.COMPLETED, True, "is complete"),
    ],
)
def test_emails_on_order_status_change_with_shop_settings(
    django_capture_on_commit_callbacks,
    shop_settings,
    payment_status,
    new_payment_status,
    email_sent,
    subject,
):
    assert len(mail.outbox) == 0
    with django_capture_on_commit_callbacks(execute=True):
        new_order = baker.make(Order, status=payment_status, email="test@test.com")
    # email to customer and admins
    assert len(mail.outbox) == 2

    with django_capture_on_commit_callbacks(execute=True):
        new_order.status = new_payment_status
        new_order.save()
    if email_sent:
        # emails to customer only, with the shop reply-to address
        assert len(mail.outbox) == 3
        assert mail.outbox[2].to == ["test@test.com"]
        assert mail.outbox[2].reply_to == ["shop@test.com"]
        assert mail.outbox[2].subject == f"PINS shop order {new_order.ref} {subject}"
    else:
        assert len(mail.outbox) == 2


def test_emails_not_sent_until_transaction_commits(
    django_capture_on_commit_callbacks, shop_settings
):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        baker.make(Order, status=Order.Status.PROCESSING, email="test@test.com")
    assert len(mail.outbox) == 0
    # one callback each for the customer and admin emails, and one to email any
    # dispatchers (once the order's items have been created)
    assert len(callbacks) == 3

    for callback in callbacks:
        callback()
    # the order has no items, so no dispatchers are emailed
    assert len(mail.outbox) == 2


def test_email_send_failure_is_logged_not_raised(
    django_capture_on_commit_callbacks, caplog
):
    with patch(
        "shop.signals.EmailMultiAlternatives.send", side_effect=SMTPException("Mail error")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            new_order = baker.make(
                Order, status=Order.Status.PROCESSING, email="test@test.com"
            )

    assert Order.objects.filter(id=new_order.id).exists()
    assert len(mail.outbox) == 0
    assert (
        f"Error sending email 'PINS shop order {new_order.ref} has been received' "
        "to ['test@test.com']" in caplog.text
    )


def test_order_email_links(django_capture_on_commit_callbacks):
    # links include the scheme, so email clients make them clickable
    with django_capture_on_commit_callbacks(execute=True):
        order = baker.make(Order, status=Order.Status.PROCESSING, email="test@test.com")
    status_url = f"https://podencosinneed.org/shop/order/{order.token}/"
    assert f"View the status of your order: {status_url}" in mail.outbox[0].body


@pytest.mark.parametrize(
    "signal,subject",
    [
        (stripe_signals.dispute_created, "PINS shop order {ref}: payment disputed"),
        (stripe_signals.dispute_closed, "PINS shop order {ref}: dispute closed"),
    ],
)
def test_dispute_emails(shop_settings, order, signal, subject, django_capture_on_commit_callbacks):
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        signal.send(sender=None, order=order, dispute=None, message="Dispute message")
    (email,) = mail.outbox
    assert email.to == ["admin@test.com", "another_admin@test.com"]
    assert email.subject == subject.format(ref=order.ref)
    assert email.body == (
        "Dispute message\n\n"
        f"View the order: https://podencosinneed.org/admin/shop/orders/{order.pk}/"
    )


def test_dispute_emails_no_notify_addresses(order, django_capture_on_commit_callbacks):
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        stripe_signals.dispute_created.send(
            sender=None, order=order, dispute=None, message="Dispute message"
        )
    assert mail.outbox == []


def test_account_deauthorized_email(shop_settings, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        stripe_signals.account_deauthorized.send(sender=None, account_id="acct_1")
    (email,) = mail.outbox
    assert email.to == ["admin@test.com", "another_admin@test.com"]
    assert email.subject == "PINS shop: Stripe account disconnected, card payments are unavailable"
    assert "The Stripe account acct_1 has been disconnected" in email.body
    assert "https://podencosinneed.org/stripe/connect/" in email.body


def test_account_deauthorized_no_notify_addresses(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        stripe_signals.account_deauthorized.send(sender=None, account_id="acct_1")
    assert mail.outbox == []
