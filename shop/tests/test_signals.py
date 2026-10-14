from smtplib import SMTPException
from unittest.mock import patch

import pytest
from model_bakery import baker

from django.conf import settings
from django.core import mail

from salesman.core.utils import get_salesman_model


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


def test_product_variant_price_set_from_product(product):
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=None
    )
    assert variant.price == 12


def test_delete_basket_item_updates_stock(basket):
    # item product variant has 5 in stock initially
    # basket items contains 2, reduces stock to 3
    basket_item = basket.items.first()
    variant = basket_item.product
    assert variant.stock == 3
    # deleting the basket item puts the quanity back in stock
    basket_item.delete()
    assert variant.stock == 5


@pytest.mark.parametrize(
    "payment_status,body_text",
    [
        (
            Order.Status.HOLD,
            "Your order will be completed when payment has been received",
        ),
        (Order.Status.PROCESSING, "Your order is being processed"),
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
    assert customer_email.subject == f"Order '{new_order.ref}' has been received"
    assert body_text in customer_email.body


@pytest.mark.parametrize(
    "payment_status,body_text",
    [
        (
            Order.Status.HOLD,
            "Your order will be completed when payment has been received",
        ),
        (Order.Status.PROCESSING, "Your order is being processed"),
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
    assert customer_email.subject == f"Order '{new_order.ref}' has been received"

    admin_email = mail.outbox[1]
    assert admin_email.to == ["admin@test.com", "another_admin@test.com"]
    assert admin_email.reply_to == ["shop@test.com"]
    assert admin_email.subject == f"New shop order '{new_order.ref}'"
    assert admin_email.body == "A new shop order has been received."


@pytest.mark.parametrize(
    "payment_status,new_payment_status,email_sent,subject",
    [
        (Order.Status.HOLD, Order.Status.HOLD, False, None),
        (Order.Status.HOLD, Order.Status.PROCESSING, True, "is being processed"),
        (Order.Status.HOLD, Order.Status.COMPLETED, True, "is completed"),
        (Order.Status.PROCESSING, Order.Status.COMPLETED, True, "is completed"),
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
        assert mail.outbox[1].subject == f"Order '{new_order.ref}' {subject}"
    else:
        assert len(mail.outbox) == 1


@pytest.mark.parametrize(
    "payment_status,new_payment_status,email_sent,subject",
    [
        (Order.Status.HOLD, Order.Status.HOLD, False, None),
        (Order.Status.HOLD, Order.Status.PROCESSING, True, "is being processed"),
        (Order.Status.HOLD, Order.Status.COMPLETED, True, "is completed"),
        (Order.Status.PROCESSING, Order.Status.COMPLETED, True, "is completed"),
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
        assert mail.outbox[2].subject == f"Order '{new_order.ref}' {subject}"
    else:
        assert len(mail.outbox) == 2


def test_emails_not_sent_until_transaction_commits(
    django_capture_on_commit_callbacks, shop_settings
):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        baker.make(Order, status=Order.Status.PROCESSING, email="test@test.com")
    assert len(mail.outbox) == 0
    # one callback each for the customer and admin emails
    assert len(callbacks) == 2

    for callback in callbacks:
        callback()
    assert len(mail.outbox) == 2


def test_email_send_failure_is_logged_not_raised(
    django_capture_on_commit_callbacks, caplog
):
    with patch(
        "shop.signals.EmailMessage.send", side_effect=SMTPException("Mail error")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            new_order = baker.make(
                Order, status=Order.Status.PROCESSING, email="test@test.com"
            )

    assert Order.objects.filter(id=new_order.id).exists()
    assert len(mail.outbox) == 0
    assert (
        f"Error sending email 'Order '{new_order.ref}' has been received' "
        "to ['test@test.com']" in caplog.text
    )
