"""
Products without a stock limit (e.g. competition entries, or items made to
order): stock isn't counted, and they're never out of stock.
"""

import json

import pytest
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from ..models import UNLIMITED_SHARED_MESSAGE, ProductVariant, stock_reminders
from .factories import PRODUCT_FORM_DEFAULTS

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")


@pytest.fixture
def entries(product):
    product.unlimited_stock = True
    product.save()
    return product


@pytest.fixture
def entry(entries):
    # (no stock: it isn't counted)
    return baker.make("shop.ProductVariant", product=entries, variant_name="", stock=0, price=2)


def stock(variant):
    return ProductVariant.objects.get(id=variant.id).stock


def test_variant(entry):
    assert entry.available is None
    assert entry.has_stock_for(1000)
    assert entry.has_stock_for(1000, in_basket=5)
    assert entry.stock_note() == ""
    assert entry.stock_display() == "No limit"
    assert entry.stock_reminder() is None
    assert stock_reminders([entry]) == []
    entry.live = False
    assert entry.stock_display() == "No limit (not live)"


def test_product_out_of_stock(entries, entry):
    # never out of stock, unless it has no live variants
    assert not entries.out_of_stock()
    entry.live = False
    entry.save()
    assert entries.out_of_stock()


def test_basket_doesnt_count_stock(entry):
    # adding, changing and removing items doesn't change the stock
    basket = baker.make(Basket)
    basket.add(entry, quantity=500)
    assert stock(entry) == 0
    item = basket.items.get()
    item.quantity = 600
    item.save()
    assert stock(entry) == 0
    basket.remove(item.ref)
    assert stock(entry) == 0


def test_order_doesnt_count_stock(entry):
    # (an order that's deleted returns its items' stock, see signals)
    basket = baker.make(Basket, extra={"name": "Ann"}, shipping_method="none")
    basket.add(entry, quantity=3)
    order = Order.objects.create_from_basket(basket, None)
    order.delete()
    assert stock(entry) == 0


def test_shop_page_and_quantity(client, entries, entry):
    content = client.get(reverse("shop:product_detail", args=(entries.id,))).content.decode()
    # no stock note, no limit for the quantity buttons
    assert "left" not in content
    assert "Out of stock" not in content
    assert f'value="{entry.id}" data-in-basket="0"' in content
    assert "data-available" not in content
    # more than the stock (0): no limit, no message
    content = client.get(
        reverse("shop:increase_quantity", args=(entries.id,)),
        {"variant_id": entry.id, "quantity": 99},
    ).content.decode()
    assert 'value="100"' in content
    assert "available</div>" not in content
    assert "max=" not in content


def test_shop_page_options(client, entries, entry):
    other = baker.make("shop.ProductVariant", product=entries, variant_name="Junior", stock=0, price=1)
    entry.variant_name = "Adult"
    entry.save()
    content = " ".join(client.get(reverse("shop:product_detail", args=(entries.id,))).content.decode().split())
    # neither option is disabled (or out of stock)
    assert f'<option value="{other.id}" data-in-basket="0" data-name="Junior">' in content
    assert " disabled" not in content.split("</select>")[0].split("<select")[1]


def test_add_to_basket(client, entries, entry):
    resp = client.post(
        reverse("shop:add_to_basket", args=(entries.id,)),
        {"variant_id": entry.id, "quantity": 250},
    )
    content = resp.content.decode()
    assert "Added!" in content
    assert 'aria-label="Basket (250 items)"' in content
    assert stock(entry) == 0
    # the added variant stays selected, and the basket has no max for it
    basket = Basket.objects.get()
    resp = client.get(reverse("shop:basket"))
    (item,) = resp.context["basket"]["items"][entries.identifier]
    assert item["max_quantity"] is None
    assert 'value="250">' in resp.content.decode()
    # (in the basket, its quantity can still be increased)
    content = client.get(
        reverse("shop:increase_quantity", args=(entries.id,)),
        {"variant_id": entry.id, "quantity": 250, "ref": "basket"},
    ).content.decode()
    assert 'value="251">' in content
    assert basket.items.count() == 1


# The admin


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    return client


def product_form_data(product, variant, **data):
    form = {
        "category": product.category.id,
        "name": product.name,
        "price": str(product.price),
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "live": "on",
        **PRODUCT_FORM_DEFAULTS,
        "stock_shown": "0",
        "variants-TOTAL_FORMS": "1",
        "variants-INITIAL_FORMS": "1",
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
        "variants-0-id": str(variant.id),
        "variants-0-price": str(variant.price),
        "variants-0-stock": str(variant.stock),
        "variants-0-stock_shown": str(variant.stock),
        "variants-0-pack_size": "1",
        "variants-0-live": "on",
        "variants-0-ORDER": "1",
    }
    form.update(data)
    return {key: value for key, value in form.items() if value != ""}


def edit_url(product):
    return reverse("wagtailsnippets_shop_product:edit", args=(product.id,))


def test_admin_set_unlimited(admin_client, product):
    variant = baker.make("shop.ProductVariant", product=product, stock=4, price=2)
    resp = admin_client.post(edit_url(product), product_form_data(product, variant, unlimited_stock="on"))
    assert resp.status_code == 302
    product.refresh_from_db()
    assert product.unlimited_stock
    # the product page: no stock fields for its variants
    content = admin_client.get(edit_url(product)).content.decode()
    assert 'name="variants-0-stock"' not in content
    assert 'name="unlimited_stock"' in content


def test_admin_unlimited_and_shared(admin_client, product):
    variant = baker.make("shop.ProductVariant", product=product, stock=4, price=2)
    resp = admin_client.post(
        edit_url(product),
        product_form_data(product, variant, unlimited_stock="on", shares_stock="on"),
    )
    assert resp.status_code == 200
    assert UNLIMITED_SHARED_MESSAGE.replace("'", "&#x27;") in resp.content.decode()
    product.refresh_from_db()
    assert not product.unlimited_stock


def test_admin_variant_page(admin_client, entry):
    content = admin_client.get(
        reverse("wagtailsnippets_shop_productvariant:edit", args=(entry.id,))
    ).content.decode()
    assert "This product has no stock limit" in content
    assert 'name="stock"' not in content


def test_admin_variants_list(admin_client, entry):
    content = admin_client.get(reverse("wagtailsnippets_shop_productvariant:list")).content.decode()
    assert "No limit" in content


def test_admin_products_list_links_to_variants(admin_client, entry):
    # (not about stock: the Products list's variant count links to the
    # product's variants)
    product = entry.product
    content = admin_client.get(reverse("wagtailsnippets_shop_product:list")).content.decode()
    url = reverse("wagtailsnippets_shop_productvariant:list")
    assert f'<a href="{url}?product={product.id}">1 live (1 total)</a>' in content
    resp = admin_client.get(f"{url}?product={product.id}")
    assert list(resp.context["object_list"]) == [entry]


def test_admin_stock_fields_script(admin_client, product):
    # (the product page shows only the stock fields that apply)
    content = admin_client.get(edit_url(product)).content.decode()
    assert "shop/js/admin_stock_fields.js" in content
