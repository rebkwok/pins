"""Products' web addresses: by slug (from the name)"""

import pytest
from model_bakery import baker

from ..models import Product, unique_product_slug

pytestmark = pytest.mark.django_db


def make(category, name, **fields):
    return Product.objects.create(category=category, name=name, price=1, **fields)


def test_slug_from_name(category):
    product = make(category, "PINS hoodie (unisex, organic cotton)")
    assert product.slug == "pins-hoodie-unisex-organic-cotton"
    assert product.get_absolute_url() == "/shop/product/pins-hoodie-unisex-organic-cotton/"


def test_slug_numbered(category):
    # (two products with the same name)
    assert make(category, "Mug").slug == "mug"
    assert make(category, "Mug").slug == "mug-2"
    assert make(category, "mug!").slug == "mug-3"


def test_slug_without_letters(category):
    assert make(category, "2026").slug == "2026"
    assert make(category, "!!!").slug == "product"


def test_slug_kept_when_name_changes(category):
    # (so links to it keep working)
    product = make(category, "Mug")
    product.name = "Big mug"
    product.save()
    product.refresh_from_db()
    assert product.slug == "mug"


def test_slug_given(category):
    assert make(category, "Mug", slug="podenco-mug").slug == "podenco-mug"


def test_unique_product_slug_ignores_itself(category):
    product = make(category, "Mug")
    assert unique_product_slug("Mug", product.pk) == "mug"
    assert unique_product_slug("Mug") == "mug-2"


def test_not_in_the_admin(admin_client, category):
    # (always made from the name)
    from django.urls import reverse

    content = admin_client.get(reverse("wagtailsnippets_shop_product:add")).content.decode()
    assert 'name="name"' in content
    assert 'name="slug"' not in content


def test_product_page(client, category):
    product = make(category, "Mug")
    baker.make("shop.ProductVariant", product=product, stock=1)
    resp = client.get("/shop/product/mug/")
    assert resp.status_code == 200
    assert resp.context["product"] == product
