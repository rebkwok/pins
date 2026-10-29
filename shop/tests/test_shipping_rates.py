"""Shipping rates (see also test_modifiers for the basket's shipping cost)"""

import json
from decimal import Decimal

import pytest
from django.urls import reverse
from model_bakery import baker
from wagtail.admin.panels import get_edit_handler

from ..models import Product, ShippingRate

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(client):
    user = baker.make("auth.User", is_superuser=True, is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def standard():
    # (made by the migrations)
    return ShippingRate.objects.get(name="Standard")


def test_standard_rate(standard):
    assert standard.default
    assert standard.amount == Decimal("4.99")
    assert ShippingRate.get_default() == standard
    assert str(standard) == "Standard (£4.99)"
    assert standard.cost() == "£4.99"


def test_one_default_rate(standard):
    small = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    assert not small.default
    # ticking another rate's default unticks the current one
    small.default = True
    small.save()
    standard.refresh_from_db()
    assert not standard.default
    assert ShippingRate.get_default() == small


def test_first_rate_is_default(standard):
    standard.delete()
    rate = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    assert rate.default


def test_default_rate_cant_be_unticked(standard):
    standard.default = False
    with pytest.raises(Exception) as error:
        standard.full_clean()
    assert "There must be a default rate" in str(error.value)
    # (a new rate, or one that isn't the default, can be saved without it)
    ShippingRate(name="Small items", amount=Decimal("3.50")).full_clean()


def test_products_get_the_default_rate(standard, category):
    product = baker.make(Product, category=category)
    assert product.shipping_rate == standard
    assert standard.products_count() == 1
    # (not products that don't need shipping)
    entry = baker.make(Product, category=category, requires_shipping=False)
    assert entry.shipping_rate is None


def test_delivery_cost(standard, product):
    assert product.delivery_cost == Decimal("4.99")
    product.shipping_rate = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    assert product.delivery_cost == Decimal("3.50")
    # (the default rate if the product has none)
    product.shipping_rate = None
    assert product.delivery_cost == Decimal("4.99")
    product.requires_shipping = False
    assert product.delivery_cost is None
    # (no rates)
    product.requires_shipping = True
    ShippingRate.objects.update(default=False)
    assert product.delivery_cost is None


def product_form(data=None, instance=None):
    form_class = get_edit_handler(Product).get_form_class()
    return form_class(data, instance=instance)


def test_new_product_form_starts_with_default_rate(standard):
    assert product_form().initial["shipping_rate"] == standard.pk


def test_product_form_existing_product_keeps_rate(product):
    small = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    product.shipping_rate = small
    product.save()
    assert product_form(instance=product)["shipping_rate"].value() == small.pk


def test_product_form_rate_required_for_shipping(category):
    data = {
        "category": category.pk,
        "name": "Mug",
        "price": "10",
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "requires_shipping": "on",
        "variants-TOTAL_FORMS": "0",
        "variants-INITIAL_FORMS": "0",
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
        "product_images-TOTAL_FORMS": "0",
        "product_images-INITIAL_FORMS": "0",
        "product_images-MIN_NUM_FORMS": "0",
        "product_images-MAX_NUM_FORMS": "1000",
    }
    form = product_form(data)
    assert not form.is_valid()
    assert form.errors["shipping_rate"] == [
        "Choose a shipping rate for a product that needs shipping."
    ]
    # not needed for a product that doesn't need shipping
    del data["requires_shipping"]
    assert "shipping_rate" not in product_form(data).errors


# Deleting rates


def delete(client, rate):
    return client.post(reverse("wagtailsnippets_shop_shippingrate:delete", args=(rate.pk,)))


def test_delete_unused_rate(client, admin, standard):
    small = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    resp = delete(client, small)
    assert resp.status_code == 302
    assert not ShippingRate.objects.filter(pk=small.pk).exists()


def test_cant_delete_default_rate(client, admin, standard):
    resp = delete(client, standard)
    assert resp.url == reverse("wagtailsnippets_shop_shippingrate:edit", args=(standard.pk,))
    assert ShippingRate.objects.filter(pk=standard.pk).exists()
    messages = [str(message) for message in resp.wsgi_request._messages]
    assert messages == [
        "Standard is the default rate, so can't be deleted: make another rate the default first."
    ]


def test_cant_delete_rate_in_use(client, admin, standard, product):
    small = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    product.shipping_rate = small
    product.save()
    resp = delete(client, small)
    assert ShippingRate.objects.filter(pk=small.pk).exists()
    messages = [str(message) for message in resp.wsgi_request._messages]
    assert messages == [
        "Small items can't be deleted: 1 product uses it. Give it another rate first."
    ]


def test_cant_bulk_delete_rates_in_use(client, admin, standard, product):
    small = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    resp = client.post(
        reverse(
            "wagtail_bulk_action",
            args=("shop", "shippingrate", "delete"),
        )
        + f"?id={standard.pk}&id={small.pk}"
    )
    assert resp.url == reverse("wagtailsnippets_shop_shippingrate:list")
    assert ShippingRate.objects.count() == 2


def test_shipping_rates_list(client, admin, standard, product):
    resp = client.get(reverse("wagtailsnippets_shop_shippingrate:list"))
    assert resp.status_code == 200
    assert "Standard" in resp.content.decode()


# The product page


def test_product_page_delivery_cost(client, product):
    url = reverse("shop:product_detail", args=(product.pk,))
    content = client.get(url).content.decode()
    assert "UK delivery £4.99." in content
    assert reverse("shop:faqs") in content
    product.shipping_rate = ShippingRate.objects.create(name="Free", amount=0)
    product.save()
    assert "UK delivery free." in client.get(url).content.decode()
    product.requires_shipping = False
    product.save()
    assert "UK delivery" not in client.get(url).content.decode()


def test_products_list_shipping_column(client, admin, product):
    assert product.shipping_display() == "£4.99"
    product.requires_shipping = False
    assert product.shipping_display() == "Not shipped"
    # (no rates)
    product.requires_shipping = True
    product.shipping_rate = None
    ShippingRate.objects.update(default=False)
    assert product.shipping_display() == "-"
    resp = client.get(reverse("wagtailsnippets_shop_product:list"))
    assert "£4.99" in resp.content.decode()
