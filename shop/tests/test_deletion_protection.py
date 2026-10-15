"""
Product variants that have been ordered or are in customers' baskets can't be
deleted, and nor can products (or category/shop pages) with such variants.
Salesman protects variants in baskets and a signal protects ordered variants
(raising ProtectedError); the admin checks first and shows a message, rather
than a server error.
"""
import json

import pytest
from model_bakery import baker

from django.contrib.messages import get_messages
from django.db import transaction
from django.db.models import ProtectedError
from django.urls import reverse
from wagtail.admin.panels import get_edit_handler

from ..models import Product, ProductVariant, protected_variants_message

pytestmark = pytest.mark.django_db

MESSAGE = (
    "Test Product - Small can't be deleted because it is in customers' baskets. "
    "Make it not live instead, so it can't be added to any more baskets."
)


@pytest.fixture
def variant(basket):
    # the basket fixture has 2 of this variant
    yield basket.items.first().product


@pytest.fixture
def ordered_variant(order, basket):
    # the variant has been ordered, and isn't in a basket any more
    basket.clear()
    yield order.items.first().product


ORDERED_MESSAGE = (
    "Test Product - Small can't be deleted because it has been ordered. "
    "Make it not live instead, so it can't be added to any more baskets."
)


@pytest.fixture
def admin_client(client):
    user = baker.make("auth.User", is_superuser=True, is_staff=True)
    client.force_login(user)
    yield client


def messages_for(resp):
    return [str(m) for m in get_messages(resp.wsgi_request)]


# Model deletion


def test_delete_variant_in_basket(variant):
    # Salesman's protection. Deletion runs in a transaction; give it its own so
    # the test's transaction can continue after the error
    with pytest.raises(ProtectedError, match="because it is added to basket"):
        with transaction.atomic():
            variant.delete()
    assert ProductVariant.objects.filter(id=variant.id).exists()


def test_delete_product_with_variant_in_basket(variant):
    product = variant.product
    with pytest.raises(ProtectedError):
        with transaction.atomic():
            product.delete()
    assert Product.objects.filter(id=product.id).exists()
    assert ProductVariant.objects.filter(id=variant.id).exists()


def test_delete_variant_not_in_basket(product):
    variant = baker.make("shop.ProductVariant", product=product)
    variant.delete()
    assert not ProductVariant.objects.filter(id=variant.id).exists()


def test_delete_variant_after_basket_cleared(basket, variant):
    basket.clear()
    variant.delete()
    assert not ProductVariant.objects.filter(id=variant.id).exists()


def test_message_for_several_variants(basket, product):
    other = baker.make("shop.ProductVariant", product=product, variant_name="Large", stock=5)
    basket.add(other, quantity=1)
    assert protected_variants_message(product.variants.all()) == (
        "Test Product - Small, Test Product - Large can't be deleted because they "
        "are in customers' baskets. Make them not live instead, so they can't be "
        "added to any more baskets."
    )


# Admin


def test_admin_delete_variant_snippet(admin_client, variant):
    url = reverse("wagtailsnippets_shop_productvariant:delete", args=(variant.id,))
    resp = admin_client.post(url)
    assert resp.status_code == 302
    assert resp.url == reverse(
        "wagtailsnippets_shop_productvariant:edit", args=(variant.id,)
    )
    assert messages_for(resp) == [MESSAGE]
    assert ProductVariant.objects.filter(id=variant.id).exists()


def test_admin_delete_variant_snippet_not_in_basket(admin_client, product):
    variant = baker.make("shop.ProductVariant", product=product)
    url = reverse("wagtailsnippets_shop_productvariant:delete", args=(variant.id,))
    admin_client.post(url)
    assert not ProductVariant.objects.filter(id=variant.id).exists()


def test_admin_bulk_delete_variant_snippets(admin_client, variant, product):
    other = baker.make("shop.ProductVariant", product=product, variant_name="Large")
    url = reverse(
        "wagtail_bulk_action", args=("shop", "productvariant", "delete")
    ) + f"?id={variant.id}&id={other.id}"
    resp = admin_client.post(url)
    assert resp.status_code == 302
    assert messages_for(resp) == [MESSAGE]
    assert ProductVariant.objects.filter(id__in=[variant.id, other.id]).count() == 2


def test_admin_delete_product_snippet(admin_client, variant):
    product = variant.product
    url = reverse("wagtailsnippets_shop_product:delete", args=(product.id,))
    resp = admin_client.post(url)
    assert resp.status_code == 302
    assert messages_for(resp) == [MESSAGE]
    assert Product.objects.filter(id=product.id).exists()


def test_admin_delete_category_page(admin_client, variant):
    category_page = variant.product.category_page
    url = reverse("wagtailadmin_pages:delete", args=(category_page.id,))
    resp = admin_client.post(url)
    assert resp.status_code == 302
    assert messages_for(resp) == [MESSAGE]
    assert type(category_page).objects.filter(id=category_page.id).exists()


def test_admin_delete_shop_page(admin_client, variant, shop_page):
    url = reverse("wagtailadmin_pages:delete", args=(shop_page.id,))
    resp = admin_client.post(url)
    assert resp.status_code == 302
    assert messages_for(resp) == [MESSAGE]
    assert type(shop_page).objects.filter(id=shop_page.id).exists()


def product_form_data(product, delete):
    data = {
        "category_page": product.category_page.id,
        "name": product.name,
        "price": str(product.price),
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "index": str(product.index),
        "live": "on",
        "variants-TOTAL_FORMS": str(product.variants.count()),
        "variants-INITIAL_FORMS": str(product.variants.count()),
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
    }
    for i, variant in enumerate(product.variants.all()):
        data.update(
            {
                f"variants-{i}-id": str(variant.id),
                f"variants-{i}-variant_name": variant.variant_name,
                f"variants-{i}-colour": variant.colour,
                f"variants-{i}-size": variant.size,
                f"variants-{i}-stock": str(variant.stock),
                f"variants-{i}-live": "on",
                f"variants-{i}-ORDER": str(i + 1),
            }
        )
        if variant.id in delete:
            data[f"variants-{i}-DELETE"] = "on"
    return data


def test_product_form_remove_variant_in_basket(variant):
    product = variant.product
    form_class = get_edit_handler(Product).get_form_class()
    form = form_class(product_form_data(product, delete=[variant.id]), instance=product)
    assert not form.is_valid()
    assert form.non_field_errors() == [MESSAGE]


def test_product_form_remove_variant_not_in_basket(variant):
    product = variant.product
    other = baker.make("shop.ProductVariant", product=product, variant_name="Large")
    form_class = get_edit_handler(Product).get_form_class()
    form = form_class(product_form_data(product, delete=[other.id]), instance=product)
    assert form.is_valid(), form.errors
    form.save()
    assert not ProductVariant.objects.filter(id=other.id).exists()
    assert ProductVariant.objects.filter(id=variant.id).exists()


# Ordered variants


def test_delete_ordered_variant(ordered_variant):
    with pytest.raises(ProtectedError, match="because it has been ordered"):
        with transaction.atomic():
            ordered_variant.delete()
    assert ProductVariant.objects.filter(id=ordered_variant.id).exists()


def test_delete_product_with_ordered_variant(ordered_variant):
    product = ordered_variant.product
    with pytest.raises(ProtectedError):
        with transaction.atomic():
            product.delete()
    assert Product.objects.filter(id=product.id).exists()


def test_delete_product_with_no_ordered_variants(ordered_variant, category_page):
    # A product whose variants haven't been ordered (or added to baskets) can be
    # deleted, along with its variants
    product = baker.make("shop.Product", category_page=category_page)
    variant = baker.make("shop.ProductVariant", product=product)
    product.delete()
    assert not ProductVariant.objects.filter(id=variant.id).exists()


def test_message_ordered_and_in_baskets(ordered_variant, basket, product):
    in_basket = baker.make(
        "shop.ProductVariant", product=product, variant_name="Large", stock=5
    )
    basket.add(in_basket, quantity=1)
    deletable = baker.make("shop.ProductVariant", product=product, variant_name="XL")
    assert protected_variants_message([ordered_variant, in_basket, deletable]) == (
        "Test Product - Small can't be deleted because it has been ordered. "
        "Test Product - Large can't be deleted because it is in customers' baskets. "
        "Make them not live instead, so they can't be added to any more baskets."
    )
    assert protected_variants_message([deletable]) is None


def test_message_ordered_and_in_basket_listed_once(order, basket):
    # the basket still contains the ordered variant
    variant = order.items.first().product
    assert protected_variants_message([variant]) == ORDERED_MESSAGE


def test_admin_delete_ordered_variant_snippet(admin_client, ordered_variant):
    url = reverse(
        "wagtailsnippets_shop_productvariant:delete", args=(ordered_variant.id,)
    )
    resp = admin_client.post(url)
    assert resp.status_code == 302
    assert messages_for(resp) == [ORDERED_MESSAGE]
    assert ProductVariant.objects.filter(id=ordered_variant.id).exists()


def test_admin_delete_product_with_ordered_variant(admin_client, ordered_variant):
    product = ordered_variant.product
    url = reverse("wagtailsnippets_shop_product:delete", args=(product.id,))
    resp = admin_client.post(url)
    assert resp.status_code == 302
    assert messages_for(resp) == [ORDERED_MESSAGE]
    assert Product.objects.filter(id=product.id).exists()


def test_admin_delete_product_with_no_ordered_variants(admin_client, category_page):
    product = baker.make("shop.Product", category_page=category_page)
    baker.make("shop.ProductVariant", product=product)
    url = reverse("wagtailsnippets_shop_product:delete", args=(product.id,))
    admin_client.post(url)
    assert not Product.objects.filter(id=product.id).exists()


def test_admin_delete_category_page_with_ordered_variant(admin_client, ordered_variant):
    category_page = ordered_variant.product.category_page
    url = reverse("wagtailadmin_pages:delete", args=(category_page.id,))
    resp = admin_client.post(url)
    assert messages_for(resp) == [ORDERED_MESSAGE]
    assert type(category_page).objects.filter(id=category_page.id).exists()


def test_product_form_remove_ordered_variant(ordered_variant):
    product = ordered_variant.product
    form_class = get_edit_handler(Product).get_form_class()
    data = product_form_data(product, delete=[ordered_variant.id])
    form = form_class(data, instance=product)
    assert not form.is_valid()
    assert form.non_field_errors() == [ORDERED_MESSAGE]

