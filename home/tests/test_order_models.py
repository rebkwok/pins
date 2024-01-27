import datetime

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from model_bakery import baker

import pytest

from .conftest import OrderFormPageFactory
from ..models import OrderFormField

pytestmark = pytest.mark.django_db


def test_product_variant_slug(order_form_page):
    pv = baker.make("home.ProductVariant", page=order_form_page, name="test product", cost=5, item_count=1)
    assert pv.slug == "pv__test_product_1"

    pv1 = baker.make("home.ProductVariant", page=order_form_page, name="test product", cost=2, item_count=1)
    assert pv1.slug == "pv__test_product_2"


def test_order_form_with_invalid_voucher_code(order_form_page):
    # invalid (not active)
    baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="foo", amount=2, active=False
    )
    # valid (so voucher_code is a displayed field)
    baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="bar", amount=2, active=True
    )
    form_class = order_form_page.get_form_class()
    form = form_class(
        {
            "name": "Minnie Mouse", 
            "email_address": "m@mouse.com", 
            "pv__test_product": 1,
            "voucher_code": "foo",
            "g-recaptcha-response": "PASSED"
        },
        page=order_form_page
    )
    assert form.is_valid()
    assert "voucher_code" not in form.cleaned_data


def test_order_form_with_valid_voucher_code(order_form_page):
    baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="foo", amount=2, active=True
    )
    form_class = order_form_page.get_form_class()
    form = form_class(
        {
            "name": "Minnie Mouse", 
            "email_address": "m@mouse.com", 
            "pv__test_product": 1,
            "voucher_code": "foo",
            "g-recaptcha-response": "PASSED"
        },
        page=order_form_page
    )
    assert form.is_valid()
    assert "voucher_code" in form.cleaned_data


def test_order_form_with_invalid_quantity(order_form_page):
    order_form_page.total_available = 1
    form_class = order_form_page.get_form_class()
    form = form_class(
        {
            "name": "Minnie Mouse", 
            "email_address": "m@mouse.com", 
            "pv__test_product": 2,
            "g-recaptcha-response": "PASSED"
        },
        page=order_form_page
    )
    assert not form.is_valid()
    assert form.non_field_errors() == ["Quantity selected is unavailable; select a maximum of 1 total items."]


def test_order_form_page(order_form_page):
    assert order_form_page.default_total() == 12
    assert order_form_page.product_quantity_field_names == {"pv__test_product"}
    assert order_form_page.product_variant_slugs == {"pv__test_product"}

    baker.make("home.OrderFormField", label="test product 1", field_type="dropdown", page=order_form_page, default_value=0)
    baker.make("home.ProductVariant", page=order_form_page, name="test product 1", cost=10)
    order_form_page.save()
    assert order_form_page.product_quantity_field_names == {"pv__test_product", "pv__test_product_1"}
    assert order_form_page.default_total() == 12

def test_order_form_page_builder_no_email_field(home_page):
    orderformpage = OrderFormPageFactory(parent=home_page)
    builder =  orderformpage.form_builder(orderformpage.order_form_fields.all(), page=orderformpage)
    assert list(builder.formfields.keys()) == ["email", "wagtailcaptcha"]

def test_order_form_page_builder_with_email_field(home_page):
    orderformpage = OrderFormPageFactory(parent=home_page)
    baker.make("home.OrderFormField", label="Email address", field_type="email", page=orderformpage)
    builder =  orderformpage.form_builder(orderformpage.order_form_fields.all(), page=orderformpage)
    assert list(builder.formfields.keys()) == ["email_address", "wagtailcaptcha"]


def test_order_form_page_remove_variant(order_form_page):
    assert order_form_page.default_total() == 12
    assert order_form_page.product_quantity_field_names == {"pv__test_product"}
    assert order_form_page.product_variant_slugs == {"pv__test_product"}

    order_form_page.product_variants.first().delete()
    order_form_page.save()
    assert order_form_page.product_quantity_field_names == set()
    assert order_form_page.default_total() == 0


def test_order_form_page_multiple_items(order_form_page):
    # Make an order form field matching a product variant.
    baker.make("home.OrderFormField", label="test product 1", field_type="dropdown", page=order_form_page, default_value=0)
    baker.make("home.ProductVariant", page=order_form_page, name="test product 1", cost=5)
    order_form_page.save()

    data = {"name": "Donald Duck", "email": "don@duck.com", "pv__test_product": 2, "pv__test_product_1": 1}
    _, total, discount = order_form_page.get_variant_quantities_and_total(data)
    assert total == (2 * 10 + 1 * 5 + 2)
    assert discount == 0

    # quantities may be in list format in POST
    data = {"name": "Donald Duck", "email": "don@duck.com", "pv__test_product": [2], "pv__test_product_1": [1]}
    _, total, discount = order_form_page.get_variant_quantities_and_total(data)
    assert total == (2 * 10 + 1 * 5 + 2)
    assert discount == 0
    

@pytest.mark.parametrize(
    "code,voucher_active,expected_total,expected_discount",
    [   
        # valid active code
        ("foo", True, 2 * 10 + 2 - 2, 2),
        # valid active code as list
        (["foo"], True, 2 * 10 + 2 - 2, 2),
        # invalid code
        ("bar", True, 2 * 10 + 2, 0),
        # valid inactive code
        ("foo", False, 2 * 10 + 2, 0),
    ]
)
def test_order_form_page_with_voucher_code(order_form_page, code, voucher_active, expected_total, expected_discount):
    # Make an order form field matching a product variant.
    baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="foo", amount=2, active=voucher_active
    )
    data = {
        "name": "Donald Duck", "email": "don@duck.com", "pv__test_product": 2,
        "voucher_code": code
    }
    _, total, discount = order_form_page.get_variant_quantities_and_total(data)
    assert total == expected_total
    assert discount == expected_discount


def test_order_form_page_in_stock(order_form_page):
    assert order_form_page.total_available is None
    assert not order_form_page.sold_out()
    order_form_page.total_available = 1
    order_form_page.save()

    assert not order_form_page.sold_out()


def test_order_form_page_out_of_stock(order_form_page, order_form_submission):
    order_form_page.total_available = 2
    order_form_page.save()

    assert not order_form_page.sold_out()
    submission = order_form_submission()
    assert order_form_page.sold_out()


def test_order_form_page_disallowed_variants(order_form_page, order_form_submission):
    assert order_form_page.disallowed_variants() == []

    # order form page has 1 product variant, test_product, sold in quantities of 1
    order_form_page.total_available = 7
    order_form_page.save()

    # test_product and test_product_x5 are allowed, test_product_x10 is not allowed
    variant5 = baker.make("home.ProductVariant", page=order_form_page, name="test product x5", cost=45, item_count=5)
    variant10 = baker.make("home.ProductVariant", page=order_form_page, name="test product x10", cost=90, item_count=10)

    assert order_form_page.disallowed_variants() == [variant10]

    # make an order for 6
    order_form_submission({"pv__test_product": 1, "pv__test_product_x5": 1})
    assert order_form_page.get_total_quantity_ordered() == 6

    assert order_form_page.disallowed_variants() == [variant5, variant10]
    # sell out
    order_form_submission({"pv__test_product": 1})
    assert order_form_page.sold_out()
    assert order_form_page.disallowed_variants() == [order_form_page.product_variants.first(), variant5, variant10]

def test_order_form_submission(order_form_submission):
    submission = order_form_submission()
    assert not submission.paid
    assert not submission.shipped
    assert submission.email == "mickey.mouse@test.com"
    assert submission.items_ordered() == [(submission.page.product_variants.first(), 2)]

    submission.mark_paid()
    assert submission.paid
    assert not submission.shipped

    submission.mark_shipped()
    assert submission.paid
    assert submission.shipped

    submission.reset()
    assert not submission.paid
    assert not submission.shipped


@pytest.mark.parametrize(
    "paid,shipped,status,colour",
    [
       (False, False, "Payment pending", "danger"),
       (False, True, "Payment pending", "danger"),
       (True, False, "Paid", "primary"),
       (True, True, "Paid and shipped", "success"),
    ]
)
def test_order_form_submission_status(order_form_submission, paid, shipped, status, colour):
    submission = order_form_submission()
    submission.paid = paid
    submission.shipped = shipped
    submission.save()
    assert submission.status() == status
    assert submission.status_colour() == colour


def test_quantity_ordered_by_submission(order_form_page, order_form_submission):
    baker.make("home.ProductVariant", page=order_form_page, name="test product x5", cost=45, item_count=5)
    baker.make("home.ProductVariant", page=order_form_page, name="test product x10", cost=90, item_count=10)

    # make an order for 6
    submission = order_form_submission({"pv__test_product": 1, "pv__test_product_x5": 2, "pv__test_product_x10": 1})
    assert order_form_page.get_total_quantity_ordered() == 21
    assert order_form_page.quantity_ordered_by_submission(submission.form_data) == 21


@pytest.mark.parametrize(
    "total_available,quantity,is_valid,err_msg",
    [
        (None, 1, True, ""),
        (6, 1, False, f"Quantity selected is unavailable; select a maximum of 0 total items."),
        (7, 1, True, "" ),
        (10, 5, False, f"Quantity selected is unavailable; select a maximum of 4 total items."),
    ]
)
def test_quantity_submitted_is_valid(order_form_page, order_form_submission, total_available, quantity, is_valid, err_msg):
    baker.make("home.ProductVariant", page=order_form_page, name="test product x5", cost=45, item_count=5)
    baker.make("home.ProductVariant", page=order_form_page, name="test product x10", cost=90, item_count=10)

    # existing order for 6
    order_form_submission({"pv__test_product": 1, "pv__test_product_x5": 1})
    assert order_form_page.get_total_quantity_ordered() == 6

    # set available value
    order_form_page.total_available = total_available
    order_form_page.save()

    assert order_form_page.quantity_submitted_is_valid({"pv__test_product": quantity}) == (is_valid, err_msg)


def test_order_form_process_form_submission(order_form_page):
    baker.make("home.ProductVariant", page=order_form_page, name="test product x5", cost=45, item_count=5)
    order_form_page.save()
    form_class = order_form_page.get_form_class()
    form = form_class(
        {
            "name": "Minnie Mouse", 
            "email_address": "m@mouse.com", 
            "pv__test_product": 1,
            "pv__test_product_x5": 0,
            "g-recaptcha-response": "PASSED"
        },
        page=order_form_page
    )
    assert form.is_valid()
    
    assert not order_form_page.orderformsubmission_set.exists()
    order_form_page.process_form_submission(form)
    assert order_form_page.orderformsubmission_set.count() == 1

    assert len(mail.outbox) == 2
    assert mail.outbox[0].to == ["admin@test.com"]
    assert mail.outbox[0].subject == "test order"
    assert mail.outbox[0].reply_to == []
    assert mail.outbox[0].body == (
        "name: Minnie Mouse\n"
        "email_address: m@mouse.com\n"
        "test product: 1\n"
        "test product x5: 0\n"
        "Total items ordered: 1\n"
        "Total amount due: £12.00"
    )

    assert mail.outbox[1].to == ["m@mouse.com"]
    assert mail.outbox[1].subject == "test order"
    assert mail.outbox[1].reply_to == [settings.CC_EMAIL]

    assert mail.outbox[1].body == (
        "Thank you for your order!\n\n"
        "Total items ordered: 1\n"
        "Total amount due: £12.00\n"
        "Order summary:\n"
        "  - test product (1)\n"
        f"\nView your submission at https://{settings.DOMAIN}{order_form_page.orderformsubmission_set.first().get_absolute_url()}.\n"
        "If you haven't made your payment yet, you'll also find a link there."
    )


def test_order_form_process_form_submission_with_voucher_code(order_form_page):
    baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="foo", amount=2, active=True
    )
    form_class = order_form_page.get_form_class()
    form = form_class(
        {
            "name": "Minnie Mouse", 
            "email_address": "m@mouse.com", 
            "pv__test_product": 1,
            "voucher_code": "foo",
            "g-recaptcha-response": "PASSED"
        },
        page=order_form_page
    )
    assert form.is_valid()
    
    assert not order_form_page.orderformsubmission_set.exists()
    order_form_page.process_form_submission(form)
    assert order_form_page.orderformsubmission_set.count() == 1

    assert len(mail.outbox) == 2
    assert mail.outbox[0].to == ["admin@test.com"]
    assert mail.outbox[0].subject == "test order"
    assert mail.outbox[0].reply_to == []
    assert mail.outbox[0].body == (
        "name: Minnie Mouse\n"
        "email_address: m@mouse.com\n"
        "test product: 1\n"
        "Voucher code: foo\n"
        "Total items ordered: 1\n"
        "Discount: £2.00\n"
        "Total amount due: £10.00"
    )

    assert mail.outbox[1].to == ["m@mouse.com"]
    assert mail.outbox[1].subject == "test order"
    assert mail.outbox[1].reply_to == [settings.CC_EMAIL]

    assert mail.outbox[1].body == (
        "Thank you for your order!\n\n"
        "Total items ordered: 1\n"
        "Discount: £2.00\n"
        "Total amount due: £10.00\n"
        "Order summary:\n"
        "  - test product (1)\n"
        f"\nView your submission at https://{settings.DOMAIN}{order_form_page.orderformsubmission_set.first().get_absolute_url()}.\n"
        "If you haven't made your payment yet, you'll also find a link there."
    )


def test_order_form_render_landing_page(order_form_page, order_form_submission):
    submission = order_form_submission({"pv__test_product": 2})
    request = RequestFactory().get("/")
    request.session = {}
    resp = order_form_page.render_landing_page(request, submission)
    assert request.session["paypal_item_reference"] == submission.reference
    assert resp.context_data["total"] == 22
    paypal_form = resp.context_data["paypal_form"]
    assert paypal_form.initial["amount"] == 22
    assert paypal_form.initial["item_name"] == 'Order form submission: Test Order Form'
    assert paypal_form.initial["invoice"] == submission.reference
