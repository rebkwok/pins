import pytest
from model_bakery import baker

from django.core import mail

from salesman.core.utils import get_salesman_model


Order = get_salesman_model("Order")

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop_settings():
    baker.make(
        "shop.ShopSettings",
        notify_email_addresses="admin@test.com, another_admin@test.com",
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
def test_emails_on_order_creation_no_shop_email_setting(payment_status, body_text):
    new_order = baker.make(Order, status=payment_status, email="test@test.com")
    # email to customer only
    assert len(mail.outbox) == 1
    customer_email = mail.outbox[0]
    assert customer_email.to == ["test@test.com"]
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
    payment_status, body_text, shop_settings
):
    new_order = baker.make(Order, status=payment_status, email="test@test.com")
    assert len(mail.outbox) == 2
    customer_email = mail.outbox[0]
    assert customer_email.to == ["test@test.com"]
    assert customer_email.subject == f"Order '{new_order.ref}' has been received"

    admin_email = mail.outbox[1]
    admin_email.to = ["admin@test.com", "another_admin@test.com"]
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
    payment_status, new_payment_status, email_sent, subject
):
    assert len(mail.outbox) == 0
    new_order = baker.make(Order, status=payment_status, email="test@test.com")
    # email to customer only
    assert len(mail.outbox) == 1

    new_order.status = new_payment_status
    new_order.save()
    if email_sent:
        assert len(mail.outbox) == 2
        assert mail.outbox[1].to == ["test@test.com"]
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
    shop_settings, payment_status, new_payment_status, email_sent, subject
):
    assert len(mail.outbox) == 0
    new_order = baker.make(Order, status=payment_status, email="test@test.com")
    # email to customer and admins
    assert len(mail.outbox) == 2

    new_order.status = new_payment_status
    new_order.save()
    if email_sent:
        # emails to customer only
        assert len(mail.outbox) == 3
        assert mail.outbox[2].to == ["test@test.com"]
        assert mail.outbox[2].subject == f"Order '{new_order.ref}' {subject}"
    else:
        assert len(mail.outbox) == 2
