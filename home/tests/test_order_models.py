import datetime

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError

from model_bakery import baker

import pytest

from .conftest import OrderFormPageFactory
from ..models import OrderShippingCost

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


def test_order_form_with_invalid_voucher_code_for_other_page(order_form_page):
    order_form_page1 = OrderFormPageFactory(title="Another page")

    # invalid (active, same code, but different page)
    baker.make(
        "home.OrderVoucher", order_form_page=order_form_page1, code="foo", amount=2, active=True
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


@pytest.mark.parametrize(
    "title,subject_title",
    [
        ("Thing Order Form", "Thing"),
        ("Thing", "Thing")
    ]
)
def test_order_form_page_subject_title(order_form_page, order_form_submission, title, subject_title):
    order_form_page.title = title
    order_form_page.save()
    assert order_form_page.subject_title == subject_title

    submission = order_form_submission()
    assert submission.page.subject_title == subject_title
    

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


def test_order_form_page_disallowed_variants(order_form_page, order_form_pre_submission):
    assert order_form_page.disallowed_variants() == []

    # order form page has 1 product variant, test_product, sold in quantities of 1
    order_form_page.total_available = 7
    order_form_page.save()

    # test_product and test_product_x5 are allowed, test_product_x10 is not allowed
    variant5 = baker.make("home.ProductVariant", page=order_form_page, name="test product x5", cost=45, item_count=5)
    variant10 = baker.make("home.ProductVariant", page=order_form_page, name="test product x10", cost=90, item_count=10)

    assert order_form_page.disallowed_variants() == [variant10]

    # make an order for 6
    order_form_pre_submission({"pv__test_product": 1, "pv__test_product_x5": 1})
    assert order_form_page.get_total_quantity_ordered() == 6
    
    assert set(order_form_page.disallowed_variants()) == {variant5, variant10}
    # sell out
    order_form_pre_submission({"pv__test_product": 1})
    assert order_form_page.sold_out()
    assert set(
        order_form_page.disallowed_variants()
    ) == {order_form_page.product_variants.first(), variant5, variant10}


def test_order_form_page_disallowed_variants_by_group(order_form_page, order_form_pre_submission):
    assert order_form_page.disallowed_variants() == []

    # test_product and test_product_x5 are allowed, test_product_x10 is not allowed
    group1variant4 = baker.make("home.ProductVariant", page=order_form_page, group_name="group1", group_total_available=6, name="test product x4", cost=10, item_count=4)
    group1variant3 = baker.make("home.ProductVariant", page=order_form_page, group_name="group1", name="test product x3", cost=20, item_count=3)
    group2variant10 = baker.make("home.ProductVariant", page=order_form_page, group_total_available=10, group_name="group2", name="test product x10", cost=90, item_count=10)
    variant4 = baker.make("home.ProductVariant", page=order_form_page, variant_total_available=3, name="test product_x4", cost=90, item_count=4)

    assert order_form_page.disallowed_variants() == [variant4]

    # make an order for group1 variant 3 (and override default for pv__test_product)
    order_form_pre_submission({"pv__test_product": 0, "pv__group1_test_product_x3": 1})
    assert order_form_page.get_total_quantity_ordered() == 3
    
    # group 1 has 6 total available, one set of 3 sold, variant3 is allowed, variant4 is not sold out
    assert set(order_form_page.disallowed_variants()) == {variant4, group1variant4}
    # sell out
    order_form_pre_submission({"pv__group1_test_product_x3": 1, "pv__group2_test_product_x10": 1, "pv__test_product_x4": 4})

    assert order_form_page.sold_out()
    assert set(
        order_form_page.disallowed_variants()
    ) == {group1variant4, group1variant3, group2variant10, variant4}


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


def test_quantity_ordered_by_submission(order_form_page, order_form_pre_submission):
    baker.make("home.ProductVariant", page=order_form_page, name="test product x5", cost=45, item_count=5)
    baker.make("home.ProductVariant", page=order_form_page, name="test product x10", cost=90, item_count=10)

    # make an order for 6
    submission = order_form_pre_submission({"pv__test_product": 1, "pv__test_product_x5": 2, "pv__test_product_x10": 1})
    assert order_form_page.get_total_quantity_ordered() == 21
    assert order_form_page.quantity_ordered_by_submission(submission.form_data) == {
        'total': 21, 
        'groups': {'': 21}, 
        'variants': {
            'pv__test_product': 1, 
            'pv__test_product_x5': 10, 
            'pv__test_product_x10': 10
        }
    }


@pytest.mark.parametrize(
    "total_available,quantity,is_valid,err_msg",
    [
        (None, 1, True, ""),
        (6, 1, False, f"Quantity selected is unavailable; select a maximum of 0 total items."),
        (7, 1, True, "" ),
        (10, 5, False, f"Quantity selected is unavailable; select a maximum of 4 total items."),
    ]
)
def test_quantity_submitted_is_valid(order_form_page, order_form_pre_submission, total_available, quantity, is_valid, err_msg):
    baker.make("home.ProductVariant", page=order_form_page, name="test product x5", cost=45, item_count=5)
    baker.make("home.ProductVariant", page=order_form_page, name="test product x10", cost=90, item_count=10)

    # existing order for 6
    order_form_pre_submission({"pv__test_product": 1, "pv__test_product_x5": 1})
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
        "email_address: m@mouse.com\n\n"
        "Order summary:\n"
        "  - test product (1)\n\n"
        "Total items ordered: 1\n"
        "Total amount due: £12.00"      
    )

    assert mail.outbox[1].to == ["m@mouse.com"]
    assert mail.outbox[1].subject == "test order"
    assert mail.outbox[1].reply_to == [settings.DEFAULT_ADMIN_EMAIL]
    assert mail.outbox[1].body == (
        "Thank you for your order!\n\n"
        "Order summary:\n"
        "  - test product (1)\n\n"
        "Total items ordered: 1\n"
        "Total amount due: £12.00\n"
        f"\nView your order at https://{settings.DOMAIN}{order_form_page.orderformsubmission_set.first().get_absolute_url()}.\n"
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
        "Voucher code: foo\n\n"
        "Order summary:\n"
        "  - test product (1)\n\n"
        "Total items ordered: 1\n"
        "Discount: £2.00\n"
        "Total amount due: £10.00"
    )

    assert mail.outbox[1].to == ["m@mouse.com"]
    assert mail.outbox[1].subject == "test order"
    assert mail.outbox[1].reply_to == [settings.DEFAULT_ADMIN_EMAIL]   
    assert mail.outbox[1].body == (
        "Thank you for your order!\n\n"
        "Order summary:\n"
        "  - test product (1)\n\n"
        "Total items ordered: 1\n"
        "Discount: £2.00\n"
        "Total amount due: £10.00\n"
        f"\nView your order at https://{settings.DOMAIN}{order_form_page.orderformsubmission_set.first().get_absolute_url()}.\n"
        "If you haven't made your payment yet, you'll also find a link there."
    )


def test_order_form_render_landing_page(rf, order_form_page, order_form_submission):
    submission = order_form_submission({"pv__test_product": 2})
    request = rf.get("/")
    request.session = {}
    resp = order_form_page.render_landing_page(request, submission)
    assert request.session["paypal_item_reference"] == submission.reference
    assert resp.context_data["total"] == 22
    paypal_form = resp.context_data["paypal_form"]
    assert paypal_form.initial["amount"] == 20
    assert paypal_form.initial["shipping"] == 2
    assert paypal_form.initial["item_name"] == 'Website order: Test Order Form (2 items)'
    assert paypal_form.initial["invoice"] == submission.reference


def test_order_form_submission_paid_deactivates_one_time_voucher(order_form_page, order_form_submission):
    voucher = baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="foo", amount=2, 
        active=True, one_time_use=True
    )
    assert voucher.active
    submission = order_form_submission({"voucher_code": "foo"})

    # mark as paid, makes voucher inactive
    submission.paid = True
    submission.save()
    voucher.refresh_from_db()
    assert not voucher.active

    # make voucher active again. Saving already-paid submission doesn't deactivate it again.
    voucher.active = True
    voucher.save()
    submission.save()
    assert voucher.active


def test_order_form_submission_paid_does_not_deactivates_multiuse_voucher(order_form_page, order_form_submission):
    voucher = baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="foo", amount=2, 
        active=True, one_time_use=False
    )
    assert voucher.active
    submission = order_form_submission({"voucher_code": "foo"})

    # mark as paid, voucher still active
    submission.paid = True
    submission.save()
    voucher.refresh_from_db()
    assert voucher.active


@pytest.mark.parametrize(
    "shipping_rates,expected",
    [
        (
            [(OrderShippingCost.DEFAULT_MAX, 1)], 
            {
                OrderShippingCost.DEFAULT_MAX: ("Flat rate per order", 1)
            }
        ),
        (
            [
                (1, 1),
                (OrderShippingCost.DEFAULT_MAX, 2)
            ], 
            {   
                1: ("1 item", 1),
                OrderShippingCost.DEFAULT_MAX: ("2+ items", 2)
            }
        ),
        (
            [
                (5, 1),
                (OrderShippingCost.DEFAULT_MAX, 2)
            ], 
            {   
                5: ("1-5 items", 1),
                OrderShippingCost.DEFAULT_MAX: ("6+ items", 2)
            }
        ),
        (
            [   
                (1, 1),
                (3, 2),
                (5, 3),
                (OrderShippingCost.DEFAULT_MAX, 4)
            ], 
            {   
                1: ("1 item", 1),
                3: ("2-3 items", 2),
                5: ("4-5 items", 3),
                OrderShippingCost.DEFAULT_MAX: ("6+ items", 4)
            }
        ),
        (
            [], 
            None
        ),
    ]
)
def test_order_form_page_shipping_costs_dict(order_form_page, shipping_rates, expected):
    OrderShippingCost.objects.all().delete() 
    for max_quantity, amount in shipping_rates:
        baker.make(OrderShippingCost, order_form_page=order_form_page, max_quantity=max_quantity, amount=amount)

    assert order_form_page.shipping_costs_dict == expected

@pytest.mark.parametrize(
    "quantity_ordered,shipping_cost,total_cost",
    [
        (1, 1, 11),
        (2, 1.5, 21.5),
        (3, 1.5, 31.5),
        (4, 1.5, 41.5),
        (5, 3, 53),
        (100, 3, 1003),
    ]
)
def test_order_form_submission_get_shipping_costs(
    order_form_page, quantity_ordered, shipping_cost, total_cost
):
    OrderShippingCost.objects.all().delete() 
    baker.make(OrderShippingCost, order_form_page=order_form_page, max_quantity=1, amount=1)
    baker.make(OrderShippingCost, order_form_page=order_form_page, max_quantity=4, amount=1.5)
    baker.make(OrderShippingCost, order_form_page=order_form_page, amount=3)

    assert order_form_page.get_shipping_cost(quantity_ordered) == shipping_cost
    _, total, _ = order_form_page.get_variant_quantities_and_total({"pv__test_product": quantity_ordered})
    assert total == total_cost


def test_order_form_submission_no_shipping_cost(order_form_page):
    OrderShippingCost.objects.all().delete() 
    assert order_form_page.get_shipping_cost(5) == 0
    _, total, _ = order_form_page.get_variant_quantities_and_total({"pv__test_product": 1})
    assert total == 10


def test_order_form_submission_get_shipping_costs_no_ceiling(order_form_page):
    OrderShippingCost.objects.all().delete() 
    baker.make(OrderShippingCost, order_form_page=order_form_page, max_quantity=1, amount=1)
    baker.make(OrderShippingCost, order_form_page=order_form_page, max_quantity=4, amount=2)

    assert order_form_page.shipping_costs_dict == {
        1: ("1 item", 1),
        4: ("2-4 items", 2)
    }
    assert order_form_page.get_shipping_cost(1) == 1
    assert order_form_page.get_shipping_cost(4) == 2
    assert order_form_page.get_shipping_cost(10) == 2


def test_order_form_submission_no_shipping_cost(order_form_page):
    OrderShippingCost.objects.all().delete() 
    assert order_form_page.get_shipping_cost(5) == 0
    _, total, _ = order_form_page.get_variant_quantities_and_total({"pv__test_product": 1})
    assert total == 10