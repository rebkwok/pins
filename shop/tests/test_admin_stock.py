"""
Stock edited in the admin is applied as a change from the stock shown when the
form was loaded, so stock taken or returned by customers' baskets meanwhile
isn't overwritten.
"""
import json
import re

import pytest
from model_bakery import baker

from django.urls import reverse
from wagtail.admin.panels import get_edit_handler

from ..models import Product, ProductVariant
from .factories import PRODUCT_FORM_DEFAULTS

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    user = baker.make("auth.User", is_superuser=True, is_staff=True)
    client.force_login(user)
    yield client


@pytest.fixture
def variant(product):
    yield baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10, stock=10
    )


def stock_shown_in(html, prefix=""):
    match = re.search(
        rf'<input type="hidden" name="{prefix}stock_shown" value="(-?\d+)"', html
    )
    return int(match.group(1)) if match else None


def variant_form_data(variant, stock, stock_shown, **extra):
    data = {
        "product": variant.product.id,
        "variant_name": variant.variant_name,
        "price": "10.00",
        "stock": str(stock),
        "pack_size": "1",
        "live": "on",
        "colour": "",
        "size": "",
        **extra,
    }
    if stock_shown is not None:
        data["stock_shown"] = str(stock_shown)
    return data


def edit_variant_url(variant):
    return reverse("wagtailsnippets_shop_productvariant:edit", args=(variant.id,))


def take_stock(variant, quantity):
    # e.g. a customer adds items to their basket
    basket = baker.make("shop.Basket")
    basket.add(ProductVariant.objects.get(id=variant.id), quantity=quantity)


# Variant snippet form


def test_variant_edit_form_shows_stock(admin_client, variant):
    resp = admin_client.get(edit_variant_url(variant))
    assert resp.status_code == 200
    assert stock_shown_in(resp.content.decode()) == 10


@pytest.mark.parametrize(
    "new_stock,expected",
    [
        # the admin adds 5 while 2 are added to baskets
        (15, 13),
        # the admin removes 4
        (6, 4),
        # the admin doesn't change stock: the basket change is kept
        (10, 8),
    ],
)
def test_variant_edit_applies_stock_change(admin_client, variant, new_stock, expected):
    take_stock(variant, 2)
    resp = admin_client.post(
        edit_variant_url(variant), variant_form_data(variant, new_stock, stock_shown=10)
    )
    assert resp.status_code == 302
    variant.refresh_from_db()
    assert variant.stock == expected


def test_variant_edit_without_stock_shown(admin_client, variant):
    # If the form didn't send the stock shown, the entered stock is used
    take_stock(variant, 2)
    admin_client.post(
        edit_variant_url(variant), variant_form_data(variant, 15, stock_shown=None)
    )
    variant.refresh_from_db()
    assert variant.stock == 15


def test_variant_edit_form_errors_keep_stock_shown(admin_client, variant):
    # The form is redisplayed with the original stock shown, so saving it again
    # still applies the admin's change
    take_stock(variant, 2)
    resp = admin_client.post(
        edit_variant_url(variant),
        variant_form_data(variant, 15, stock_shown=10, price="not a price"),
    )
    assert resp.status_code == 200
    assert stock_shown_in(resp.content.decode()) == 10
    variant.refresh_from_db()
    assert variant.stock == 8


def test_variant_create(admin_client, product):
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_productvariant:add"),
        {
            "product": product.id,
            "variant_name": "Large",
            "price": "",
            "stock": "7",
            "pack_size": "1",
            "live": "on",
            "colour": "",
            "size": "",
        },
    )
    assert resp.status_code == 302
    assert ProductVariant.objects.get(variant_name="Large").stock == 7


# Product form (variants inline)


def edit_product_url(product):
    return reverse("wagtailsnippets_shop_product:edit", args=(product.id,))


def product_form_data(product, stock, stock_shown):
    variant = product.variants.get()
    return {
        "category": product.category.id,
        "name": product.name,
        "price": str(product.price),
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "index": str(product.index),
        "live": "on",
        **PRODUCT_FORM_DEFAULTS,
        "variants-TOTAL_FORMS": "1",
        "variants-INITIAL_FORMS": "1",
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
        "variants-0-id": str(variant.id),
        "variants-0-variant_name": variant.variant_name,
        "variants-0-price": "10.00",
        "variants-0-stock": str(stock),
        "variants-0-pack_size": "1",
        "variants-0-stock_shown": str(stock_shown),
        "variants-0-live": "on",
        "variants-0-colour": "",
        "variants-0-size": "",
        "variants-0-ORDER": "1",
    }


def test_product_edit_form_shows_variant_stock(admin_client, variant):
    resp = admin_client.get(edit_product_url(variant.product))
    assert resp.status_code == 200
    assert stock_shown_in(resp.content.decode(), prefix="variants-0-") == 10


@pytest.mark.parametrize("new_stock,expected", [(15, 13), (10, 8)])
def test_product_edit_applies_variant_stock_change(
    admin_client, variant, new_stock, expected
):
    take_stock(variant, 2)
    resp = admin_client.post(
        edit_product_url(variant.product),
        product_form_data(variant.product, new_stock, stock_shown=10),
    )
    assert resp.status_code == 302
    variant.refresh_from_db()
    assert variant.stock == expected


# Negative stock


def test_variant_edit_negative_stock(admin_client, variant):
    resp = admin_client.post(
        edit_variant_url(variant), variant_form_data(variant, -3, stock_shown=10)
    )
    assert resp.status_code == 200
    assert "Stock can&#x27;t be negative." in resp.content.decode()
    variant.refresh_from_db()
    assert variant.stock == 10


def test_variant_edit_reduce_to_zero(admin_client, variant):
    resp = admin_client.post(
        edit_variant_url(variant), variant_form_data(variant, 0, stock_shown=10)
    )
    assert resp.status_code == 302
    variant.refresh_from_db()
    assert variant.stock == 0


def test_variant_edit_reduction_would_be_negative_after_basket_changes(
    admin_client, variant
):
    # The admin enters 0, but 2 have been added to baskets since the page was
    # loaded, so the change (-10) would take stock to -2
    take_stock(variant, 2)
    resp = admin_client.post(
        edit_variant_url(variant), variant_form_data(variant, 0, stock_shown=10)
    )
    assert resp.status_code == 200
    assert (
        "Stock can&#x27;t be negative. It has changed from 10 to 8 since this page "
        "was loaded, because of items added to or removed from customers&#x27; "
        "baskets, so the lowest you can enter is 2."
    ) in resp.content.decode()
    variant.refresh_from_db()
    assert variant.stock == 8

    # entering the lowest allowed value sets stock to 0
    resp = admin_client.post(
        edit_variant_url(variant), variant_form_data(variant, 2, stock_shown=10)
    )
    assert resp.status_code == 302
    variant.refresh_from_db()
    assert variant.stock == 0


def test_variant_edit_unchanged_negative_stock(admin_client, variant):
    # Stock that's already negative doesn't stop other fields being changed
    ProductVariant.objects.filter(id=variant.id).update(stock=-1)
    resp = admin_client.post(
        edit_variant_url(variant),
        variant_form_data(variant, -1, stock_shown=-1, variant_name="Medium"),
    )
    assert resp.status_code == 302
    variant.refresh_from_db()
    assert variant.variant_name == "Medium"
    assert variant.stock == -1


@pytest.mark.parametrize("stock_shown", [None, ""])
def test_variant_negative_stock_without_stock_shown(admin_client, variant, stock_shown):
    data = variant_form_data(variant, -1, stock_shown=None)
    if stock_shown is not None:
        data["stock_shown"] = stock_shown
    resp = admin_client.post(edit_variant_url(variant), data)
    assert resp.status_code == 200
    variant.refresh_from_db()
    assert variant.stock == 10


def test_variant_create_negative_stock(admin_client, product):
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_productvariant:add"),
        {
            "product": product.id,
            "variant_name": "Large",
            "price": "",
            "stock": "-1",
            "pack_size": "1",
            "live": "on",
            "colour": "",
            "size": "",
        },
    )
    assert resp.status_code == 200
    assert not ProductVariant.objects.filter(variant_name="Large").exists()


def test_product_edit_variant_negative_stock(admin_client, variant):
    take_stock(variant, 2)
    resp = admin_client.post(
        edit_product_url(variant.product),
        product_form_data(variant.product, 0, stock_shown=10),
    )
    assert resp.status_code == 200
    assert "the lowest you can enter is 2" in resp.content.decode()
    variant.refresh_from_db()
    assert variant.stock == 8



def test_product_edit_duplicate_variants_message(admin_client, variant):
    product = variant.product
    data = product_form_data(product, 10, stock_shown=10)
    # add a second variant the same as the first
    data.update(
        {
            "variants-TOTAL_FORMS": "2",
            "variants-1-variant_name": variant.variant_name,
            "variants-1-price": "",
            "variants-1-stock": "1",
            "variants-1-pack_size": "1",
            "variants-1-live": "on",
            "variants-1-colour": "",
            "variants-1-size": "",
            "variants-1-ORDER": "2",
        }
    )
    resp = admin_client.post(edit_product_url(product), data)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert (
        "Two or more variants have the same name, colour and size. Each variant "
        "needs a different name, colour or size."
    ) in content
    assert "This variant has the same name, colour and size as another variant." in content
    assert "Please correct the duplicate" not in content
    assert product.variants.count() == 1


def test_variant_edit_missing_stock(admin_client, variant):
    data = variant_form_data(variant, "", stock_shown=10)
    resp = admin_client.post(edit_variant_url(variant), data)
    assert resp.status_code == 200
    assert "This field is required." in resp.content.decode()
    variant.refresh_from_db()
    assert variant.stock == 10


def test_variant_form_save_refreshes_stock(variant):
    # Saving the form directly (with commit) applies the change and refreshes
    # the instance's stock from the database
    form_class = ProductVariant.snippet_viewset.get_edit_handler().get_form_class()
    take_stock(variant, 2)
    form = form_class(variant_form_data(variant, 15, stock_shown=10), instance=variant)
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.stock == 13



# Variant names


VARIANT_NEEDS_NAME = (
    "When a product has more than one variant, each variant needs a name, colour "
    "or size, so customers can tell them apart."
)


def product_form(product, variants, delete=()):
    """
    Bound product admin form with the given variants: a list of dicts with
    optional id, variant_name, colour and size
    """
    data = {
        "category": product.category.id,
        "name": product.name,
        "price": str(product.price),
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "index": str(product.index),
        "live": "on",
        **PRODUCT_FORM_DEFAULTS,
        "variants-TOTAL_FORMS": str(len(variants)),
        "variants-INITIAL_FORMS": str(len([v for v in variants if "id" in v])),
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
    }
    for i, variant in enumerate(variants):
        data.update(
            {
                f"variants-{i}-id": str(variant.get("id", "")),
                f"variants-{i}-variant_name": variant.get("variant_name", ""),
                f"variants-{i}-colour": variant.get("colour", ""),
                f"variants-{i}-size": variant.get("size", ""),
                f"variants-{i}-stock": "1",
                f"variants-{i}-pack_size": "1",
                f"variants-{i}-stock_shown": "1" if "id" in variant else "",
                f"variants-{i}-live": "on",
                f"variants-{i}-ORDER": str(i + 1),
            }
        )
        if i in delete:
            data[f"variants-{i}-DELETE"] = "on"
    form_class = get_edit_handler(Product).get_form_class()
    return form_class(data, instance=product)


@pytest.mark.parametrize(
    "variants,valid",
    [
        # a single variant can be blank
        ([{}], True),
        ([{"variant_name": "Single"}, {"variant_name": "Pack of 3"}], True),
        # differentiated by colour/size only
        ([{"colour": "Black", "size": "S"}, {"colour": "Black", "size": "M"}], True),
        # one blank variant with another
        ([{}, {"variant_name": "Pack of 3"}], False),
        ([{"size": "S"}, {}], False),
    ],
)
def test_product_form_variant_names(product, variants, valid):
    form = product_form(product, variants)
    assert form.is_valid() == valid
    if not valid:
        formset = form.formsets["variants"]
        assert formset.non_form_errors() == [VARIANT_NEEDS_NAME]
        blank_index = next(i for i, v in enumerate(variants) if not v)
        assert formset.forms[blank_index].errors["variant_name"] == [
            "This variant needs a name, colour or size."
        ]


def test_product_form_add_named_variant_to_blank_variant(product):
    # The product has a blank variant; adding a second variant needs the first
    # one to be given a name too
    existing = baker.make("shop.ProductVariant", product=product, stock=1)
    form = product_form(product, [{"id": existing.id}, {"variant_name": "Pack of 3"}])
    assert not form.is_valid()
    form = product_form(
        product,
        [{"id": existing.id, "variant_name": "Single"}, {"variant_name": "Pack of 3"}],
    )
    assert form.is_valid(), form.errors


def test_product_form_deleting_variant_leaves_one_blank(product):
    blank = baker.make("shop.ProductVariant", product=product, stock=1)
    named = baker.make("shop.ProductVariant", product=product, variant_name="Large", stock=1)
    form = product_form(product, [{"id": blank.id}, {"id": named.id, "variant_name": "Large"}], delete=[1])
    assert form.is_valid(), form.errors


def test_product_edit_page_shows_variant_name_error(admin_client, product):
    baker.make("shop.ProductVariant", product=product, stock=1)
    form = product_form(product, [{"id": product.variants.get().id}, {"variant_name": "Pack of 3"}])
    resp = admin_client.post(edit_product_url(product), form.data)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert VARIANT_NEEDS_NAME in content
    assert "This variant needs a name, colour or size." in content
    assert product.variants.count() == 1


def variant_create_data(product, **fields):
    return {
        "product": product.id,
        "variant_name": "",
        "price": "",
        "stock": "1",
        "pack_size": "1",
        "live": "on",
        "colour": "",
        "size": "",
        **fields,
    }


def test_variant_create_blank_with_other_variants(admin_client, variant):
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_productvariant:add"),
        variant_create_data(variant.product),
    )
    assert resp.status_code == 200
    assert VARIANT_NEEDS_NAME in resp.content.decode()
    assert variant.product.variants.count() == 1


def test_variant_create_when_other_variant_is_blank(admin_client, product):
    baker.make("shop.ProductVariant", product=product, stock=1)
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_productvariant:add"),
        variant_create_data(product, variant_name="Pack of 3"),
    )
    assert resp.status_code == 200
    assert (
        "Another variant of this product has no name, colour or size; give it one first."
        in resp.content.decode()
    )
    assert product.variants.count() == 1


def test_variant_create_first_variant_blank(admin_client, product):
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_productvariant:add"), variant_create_data(product)
    )
    assert resp.status_code == 302
    assert product.variants.count() == 1


def test_variant_edit_only_variant_blank(admin_client, product):
    variant = baker.make("shop.ProductVariant", product=product, variant_name="Small", stock=10)
    resp = admin_client.post(
        edit_variant_url(variant), variant_form_data(variant, 10, stock_shown=10, variant_name="")
    )
    assert resp.status_code == 302
    variant.refresh_from_db()
    assert variant.variant_name == ""
