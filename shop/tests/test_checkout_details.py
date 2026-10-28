"""
The checkout's details: data processing consent, the delivery address (UK, or
another country), mobile number and safe place, and where they're shown.
"""

import html
from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from ..forms import UK_ONLY_NOTE, CheckoutForm, tidy_uk_postcode
from ..models import UK
from ..emails import Paragraph
from ..signals import OUTSIDE_UK_WARNING, customer_details_blocks
from ..views import checkout_view

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")

DETAILS = {
    "email": "cat@test.com",
    "email1": "cat@test.com",
    "name": "Cat",
    "phone": "07700 900123",
    "payment_method": "stripe",
    "billing_address": "-",
    "consent": "on",
}
ADDRESS = {
    "address_line1": "1 Road",
    "address_line2": "",
    "town": "Town",
    "county": "Shire",
    "postcode": "sw1a1aa",
    "country": UK,
    "safe_place": "Porch",
}


def form(shipping_method="deliver", **data):
    return CheckoutForm(
        payment_method="stripe",
        shipping_method=shipping_method,
        data={**DETAILS, **ADDRESS, "shipping_method": shipping_method, **data},
    )


# The form


def test_consent_required():
    checkout = form(consent="")
    assert not checkout.is_valid()
    assert checkout.errors["consent"] == ["Please confirm that you consent to this."]


def test_consent_label():
    label = CheckoutForm(payment_method="stripe", shipping_method="collect").fields["consent"].label
    assert '<a href="/privacy-policy/" target="_blank" rel="noopener">Data Privacy Policy</a>' in label


@pytest.mark.parametrize("field", ["address_line1", "town", "postcode"])
def test_address_required(field):
    checkout = form(**{field: ""})
    assert not checkout.is_valid()
    assert field in checkout.errors


def test_postcode_outside_uk():
    # required, but not checked (e.g. a zip code, or N/A)
    checkout = form(country="other", other_country="Ireland", postcode="")
    assert not checkout.is_valid()
    assert "postcode" in checkout.errors
    checkout = form(country="other", other_country="Ireland", postcode="N/A")
    assert checkout.is_valid(), checkout.errors
    assert checkout.formatted_address() == "1 Road\nTown\nShire\nN/A\nIreland"


def test_uk_address():
    checkout = form()
    assert checkout.is_valid(), checkout.errors
    # the postcode tidied
    assert checkout.cleaned_data["postcode"] == "SW1A 1AA"
    assert checkout.formatted_address() == "1 Road\nTown\nShire\nSW1A 1AA\nUnited Kingdom"
    details = checkout.checkout_details()
    assert details["country"] == UK
    assert details["safe_place"] == "Porch"
    assert details["phone"] == "07700 900123"
    assert details["address"]["postcode"] == "SW1A 1AA"
    assert details["consent_at"]


@pytest.mark.parametrize(
    "postcode,tidied",
    [("SW1A 1AA", "SW1A 1AA"), ("sw1a1aa", "SW1A 1AA"), ("m1  1ae", "M1 1AE"), ("B33 8TH", "B33 8TH"), ("12345", None), ("SW1A", None)],
)
def test_uk_postcodes(postcode, tidied):
    assert tidy_uk_postcode(postcode) == tidied


def test_uk_postcode_checked():
    checkout = form(postcode="12345")
    assert not checkout.is_valid()
    assert checkout.errors["postcode"] == ["Enter a UK postcode, e.g. SW1A 1AA."]


def test_other_country():
    # not rejected; the postcode isn't checked
    checkout = form(country="other", other_country="France", postcode="75001")
    assert checkout.is_valid(), checkout.errors
    assert checkout.formatted_address().endswith("75001\nFrance")
    assert checkout.checkout_details()["country"] == "France"
    # which country is needed
    checkout = form(country="other", other_country=" ")
    assert not checkout.is_valid()
    assert checkout.errors["other_country"] == ["Which country is the address in?"]


@pytest.mark.parametrize(
    "shipping_method,phone_help",
    [("deliver", "Optional: for the courier."), ("collect", "Optional: to arrange collection."), ("none", "Optional.")],
)
def test_phone_help(shipping_method, phone_help):
    checkout = CheckoutForm(payment_method="stripe", shipping_method=shipping_method)
    assert checkout.fields["phone"].help_text == phone_help


def test_collection_no_address():
    checkout = form("collect", address_line1="", town="", postcode="")
    assert checkout.is_valid(), checkout.errors
    assert checkout.formatted_address() == "-"
    assert checkout.delivery_country == ""
    assert set(checkout.checkout_details()) == {"name", "phone", "consent_at"}


# Checking out: the details become the order's


@pytest.fixture
def delivery_basket(product):
    basket = baker.make("shop.Basket", shipping_method="deliver")
    basket.add(baker.make("shop.ProductVariant", product=product, price=10, stock=5))
    basket.update(request=None)
    return basket


@mock.patch("shop.payment.PayByStripe.basket_payment")
def test_order_details(mock_basket_payment, rf, delivery_basket):
    def create_order(basket, request):
        order = Order.objects.create_from_basket(basket, request)
        return f"/order/{order.token}/"

    mock_basket_payment.side_effect = create_order
    request = rf.post(
        reverse("shop:checkout") + "?payment-method=stripe&shipping-method=deliver",
        data={**DETAILS, **ADDRESS, "shipping_method": "deliver"},
    )
    request.session = {"BASKET_ID": delivery_basket.id}
    request.user = AnonymousUser()
    resp = checkout_view(request)
    assert resp.status_code == 302
    order = Order.objects.get()
    assert (order.name, order.phone, order.safe_place, order.country) == ("Cat", "07700 900123", "Porch", UK)
    assert order.consent_at is not None
    assert order.shipping_address == "1 Road\nTown\nShire\nSW1A 1AA\nUnited Kingdom"
    assert order.extra["address"]["town"] == "Town"
    assert not order.outside_uk


def test_outside_uk(order):
    order.shipping_method = "deliver"
    order.country = "France"
    assert order.outside_uk
    order.country = UK
    assert not order.outside_uk
    # (orders from before the country was asked for)
    order.country = ""
    assert not order.outside_uk
    # collected
    order.shipping_method = "collect"
    order.country = "France"
    assert not order.outside_uk


# Where they're shown


@pytest.fixture
def delivered_order(order):
    order.shipping_method = "deliver"
    order.shipping_address = "1 Rue\nParis\nFrance"
    order.country = "France"
    order.phone = "07700 900123"
    order.safe_place = "Porch"
    order.save()
    return order


def test_email_details(delivered_order):
    assert [block.as_text() for block in customer_details_blocks(delivered_order)] == [
        "Mobile number: 07700 900123",
        "Shipping address:\n1 Rue\nParis\nFrance",
        "OUTSIDE THE UK: check that shipping has been pre-arranged with the customer "
        "and any extra costs have been paid before shipping.",
        "Safe place: Porch",
    ]
    # (the warning in bold)
    assert customer_details_blocks(delivered_order)[2].as_html() == f"<strong>{OUTSIDE_UK_WARNING}</strong>"
    delivered_order.shipping_method = "collect"
    assert customer_details_blocks(delivered_order) == [Paragraph("Mobile number: 07700 900123")]


def test_admin_order_page(client, delivered_order):
    client.force_login(baker.make("auth.User", is_superuser=True))
    content = html.unescape(client.get(reverse("shop_orders:edit", args=(delivered_order.pk,))).content.decode())
    assert '<a href="tel:07700 900123">07700 900123</a>' in content
    assert "Outside the UK: check that shipping has been arranged" in content
    assert "<dd>Porch</dd>" in content
    assert "Data processing consent" in content


def test_customer_order_page(client, delivered_order):
    content = " ".join(client.get(reverse("shop:order_status", args=(delivered_order.token,))).content.decode().split())
    assert "<dt>Safe place</dt> <dd>Porch</dd>" in content
    assert "<dt>Mobile number</dt> <dd>07700 900123</dd>" in content


def test_uk_only_note():
    assert 'please <a href="/contact-us/">contact us</a>' in UK_ONLY_NOTE
    assert UK_ONLY_NOTE.endswith("for shipping costs before placing an order.")


def test_basket_page_uk_note(client, delivery_basket):
    session = client.session
    session["BASKET_ID"] = delivery_basket.id
    session.save()
    content = client.get(reverse("shop:basket")).content.decode()
    assert f'<div class="basket-options__help shop-uk-note">{UK_ONLY_NOTE}</div>' in content


def test_checkout_page_delivery(client, delivery_basket):
    session = client.session
    session["BASKET_ID"] = delivery_basket.id
    session.save()
    content = client.get(reverse("shop:checkout") + "?payment-method=stripe&shipping-method=deliver").content.decode()
    assert "Delivery address" in content
    assert UK_ONLY_NOTE in content
    assert 'name="consent"' in content
    assert "shop/js/checkout.js" in content
