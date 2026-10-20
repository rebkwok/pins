"""
Products that don't need shipping (e.g. competition entries): baskets with
only these skip the shipping method, address and cost.
"""
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from ..forms import CheckoutForm
from ..views import basket_view, checkout_view

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")


@pytest.fixture
def entry(product):
    """A competition entry (£5), which doesn't need shipping"""
    entry_product = baker.make(
        "shop.Product",
        category_page=product.category_page,
        name="Competition entry",
        price=5,
        requires_shipping=False,
    )
    return baker.make("shop.ProductVariant", product=entry_product, stock=10)


@pytest.fixture
def entry_basket(entry):
    basket = baker.make("shop.Basket", extra={"name": "Test User"})
    basket.add(entry, quantity=2)
    basket.update(request=None)
    return basket


def basket_request(rf, url, basket):
    request = rf.get(url)
    request.session = {"BASKET_ID": basket.id}
    request.user = AnonymousUser()
    return request


# The basket


def test_product_requires_shipping_by_default(product):
    assert product.requires_shipping


def test_basket_requires_shipping(entry_basket, basket, entry):
    # only items that don't need shipping
    assert not entry_basket.requires_shipping
    assert not entry_basket.needs_delivery
    # a mixed basket needs shipping for its physical items
    basket.add(entry)
    assert basket.requires_shipping
    # an empty basket doesn't
    assert not baker.make("shop.Basket").requires_shipping


@pytest.mark.parametrize(
    "shipping_method,needs_delivery",
    [("deliver", True), ("collect", False), ("none", True)],
)
def test_basket_needs_delivery(basket, shipping_method, needs_delivery):
    # a basket with items needing shipping is delivered unless it's collected
    # (e.g. one checked out with nothing needing shipping, then had items added)
    basket.shipping_method = shipping_method
    assert basket.needs_delivery == needs_delivery


def test_no_shipping_cost(entry_basket):
    # the basket's shipping method is still the default (delivery)
    assert entry_basket.shipping_method == "deliver"
    assert entry_basket.extra_rows == {}
    assert entry_basket.total == 10


def test_mixed_basket_shipping_cost(basket, entry):
    # the flat shipping cost, for the physical items
    basket.add(entry)
    basket.shipping_method = "deliver"
    basket.update(request=None)
    assert basket.total == Decimal("20") + Decimal("5") + Decimal("4.99")


def test_basket_page(rf, entry_basket):
    resp = basket_view(basket_request(rf, reverse("shop:basket"), entry_basket))
    assert resp.context_data["shipping_methods"] == []
    assert not resp.context_data["requires_shipping"]
    content = resp.rendered_content
    assert "Nothing in your basket needs shipping." in content
    assert 'name="shipping-method"' not in content
    assert "Select shipping" not in content


def test_basket_page_mixed(rf, basket, entry):
    basket.add(entry)
    resp = basket_view(basket_request(rf, reverse("shop:basket"), basket))
    assert resp.context_data["requires_shipping"]
    content = resp.rendered_content
    assert "Select shipping method" in content
    assert 'name="shipping-method"' in content
    assert "Nothing in your basket needs shipping." not in content


def test_basket_page_after_no_shipping_checkout(rf, entry_basket, product):
    # checked out with nothing needing shipping, then an item that does is added:
    # delivery is selected
    entry_basket.shipping_method = "none"
    entry_basket.save()
    entry_basket.add(baker.make("shop.ProductVariant", product=product, stock=5))
    resp = basket_view(basket_request(rf, reverse("shop:basket"), entry_basket))
    assert resp.context_data["selected_shipping_method"] == "deliver"


# Checkout


def checkout_url(shipping_method=None):
    url = reverse("shop:checkout") + "?payment-method=stripe"
    if shipping_method:
        url += f"&shipping-method={shipping_method}"
    return url


@pytest.mark.parametrize("shipping_method", [None, "deliver", "collect", "none"])
def test_checkout_no_shipping(rf, entry_basket, shipping_method):
    # whatever the basket page sent (e.g. if the basket has changed since)
    resp = checkout_view(basket_request(rf, checkout_url(shipping_method), entry_basket))
    assert resp.status_code == 200
    entry_basket.refresh_from_db()
    assert entry_basket.shipping_method == "none"
    content = resp.rendered_content
    assert "Shipping method: No shipping needed" in content
    assert "shop-shipping-reminder" not in content
    # no shipping address
    assert 'type="hidden" name="shipping_address" value="-"' in " ".join(content.split())


@pytest.mark.parametrize("shipping_method", [None, "none", "unknown"])
def test_checkout_shipping_required(rf, basket, entry, shipping_method):
    # a basket with items needing shipping must choose delivery or collection
    basket.add(entry)
    request = basket_request(rf, checkout_url(shipping_method), basket)
    request._messages = mock.Mock()
    resp = checkout_view(request)
    assert resp.status_code == 302
    assert resp.url == reverse("shop:basket")


@mock.patch("shop.payment.PayByStripe.basket_payment")
def test_order_no_shipping(mock_basket_payment, rf, entry_basket):
    # the order is created with no shipping method or address
    def create_order(basket, request):
        order = Order.objects.create_from_basket(basket, request)
        return f"/order/{order.token}/"

    mock_basket_payment.side_effect = create_order
    request = rf.post(
        checkout_url(),
        data={
            "email": "test@test.com",
            "email1": "test@test.com",
            "name": "Test",
            "payment_method": "stripe",
            "shipping_method": "none",
            "billing_address": "-",
            "shipping_address": "-",
        },
    )
    request.session = {"BASKET_ID": entry_basket.id}
    request.user = AnonymousUser()
    resp = checkout_view(request)
    assert resp.status_code == 302
    order = Order.objects.get()
    assert order.shipping_method == "none"
    assert order.get_shipping_method_display() == "No shipping needed"
    assert not order.needs_delivery
    assert order.total == 10


@pytest.mark.parametrize(
    "shipping_method,asks_for_address", [("deliver", True), ("collect", False), ("none", False)]
)
def test_checkout_form_address(shipping_method, asks_for_address):
    form = CheckoutForm(payment_method="stripe", shipping_method=shipping_method)
    hidden = [
        field.name for field in form.helper.layout.fields if hasattr(field, "name")
    ]
    assert ("shipping_address" not in hidden) == asks_for_address


def test_order_status_no_shipping(client, entry_basket):
    entry_basket.shipping_method = "none"
    entry_basket.save()
    order = Order.objects.create_from_basket(entry_basket, None)
    content = client.get(reverse("shop:order_status", args=(order.token,))).content.decode()
    assert "Shipping method: No shipping needed" in content
    assert "Shipping address" not in content


# Removing items on the basket page (htmx)


def delete_item(client, basket, variant):
    item = next(item for item in basket.get_items() if item.product == variant)
    session = client.session
    session["BASKET_ID"] = basket.id
    session.save()
    return client.post(
        reverse("shop:delete_basket_item", args=(item.ref,)), {"product_id": variant.id}
    ).content.decode()


def test_delete_last_item_needing_shipping(client, basket, entry):
    # the shipping options are replaced: nothing left needs shipping
    basket.add(entry)
    variant = next(item.product for item in basket.get_items() if item.product != entry)
    content = " ".join(delete_item(client, basket, variant).split())
    assert '<div id="basket-checkout-options" hx-swap-oob="true">' in content
    assert "Nothing in your basket needs shipping." in content
    assert 'name="shipping-method"' not in content
    # and the shipping cost is removed from the total
    assert "<span id='total' hx-swap-oob='true'>5.00</span>" in content


def test_delete_item_still_needing_shipping(client, basket, entry):
    basket.add(entry)
    content = " ".join(delete_item(client, basket, entry).split())
    assert '<div id="basket-checkout-options" hx-swap-oob="true">' in content
    # the shipping options are still shown, keeping the basket's choice
    assert 'name="shipping-method"' in content
    assert 'id="id_collect" value="collect" checked' in content


def test_delete_last_item(client, entry_basket, entry):
    # the empty basket message replaces the options
    content = delete_item(client, entry_basket, entry)
    assert "Basket is empty." in content
    assert "basket-checkout-options" not in content
