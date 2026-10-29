import re
from decimal import Decimal

import pytest
from django.utils.text import slugify
from wagtail.test.utils.form_data import rich_text
from model_bakery import baker

from django.urls import reverse
from salesman.core.utils import get_salesman_model


pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    yield client


def breadcrumbs(content):
    """The breadcrumb labels on an admin page"""
    nav = re.search(r'<nav[^>]*aria-label="Breadcrumb">(.*?)</nav>', content, re.S).group(1)
    return [
        " ".join(re.sub(r"<[^>]+>", " ", item).split())
        for item in re.findall(r"<li.*?</li>", nav, re.S)
    ]


@pytest.mark.parametrize(
    "model,menu,label,new_label",
    [
        ("product", "Shop stock", "Products", "New: Product"),
        ("productvariant", "Shop stock", "Product variants", "New: Product variant"),
        ("sale", "Shop admin", "Sales", "New: Sale"),
    ],
)
def test_shop_breadcrumbs(
    admin_client, product, sale_with_items, model, menu, label, new_label
):
    instance = {
        "product": product,
        "productvariant": baker.make("shop.ProductVariant", product=product),
        "sale": sale_with_items,
    }[model]
    prefix = f"wagtailsnippets_shop_{model}"
    # (products and variants are under their category, and product)
    edit_crumbs = {
        "product": ["Test Category", "Test Product"],
        "productvariant": [
            "Test Category",
            "Test Product",
            # (a variant with no name, colour or size)
            "Variant",
        ],
        "sale": [str(instance)],
    }[model]
    pages = [
        (reverse(f"{prefix}:list"), []),
        (reverse(f"{prefix}:add"), [new_label]),
        (reverse(f"{prefix}:edit", args=(instance.pk,)), edit_crumbs),
    ]
    for url, last in pages:
        content = admin_client.get(url).content.decode()
        assert breadcrumbs(content) == ["Home", menu, label, *last]
        # the menu has no page, so it isn't a link
        assert not re.search(rf"<a[^>]*>\s*{menu}", content)


def test_product_variants_list_order(admin_client, product):
    # products in two categories (product's is "Test Category"), created out of
    # order
    cards = baker.make("shop.Category", title="Cards", sort_order=-1)
    mug = baker.make("shop.Product", category=product.category, name="Mug")
    calendar = baker.make("shop.Product", category=cards, name="Calendar")
    baker.make("shop.ProductVariant", product=mug, variant_name="Large", sort_order=2)
    baker.make("shop.ProductVariant", product=product, variant_name="Small", sort_order=1)
    baker.make("shop.ProductVariant", product=calendar, variant_name="Single", sort_order=1)
    baker.make("shop.ProductVariant", product=mug, variant_name="Small", sort_order=1)
    resp = admin_client.get(reverse("wagtailsnippets_shop_productvariant:list"))
    # by category, then product (in their order in the category: the mug was
    # added after Test Product), then the product's variant order
    assert [str(variant) for variant in resp.context["object_list"]] == [
        "Calendar - Single",
        "Test Product - Small",
        "Mug - Small",
        "Mug - Large",
    ]
    # no "Sort item order" for reordering all the variants together
    assert "Sort item order" not in resp.content.decode()


def test_products_list_order(admin_client, product):
    # by category (in the shop page order), then the products' order in their
    # category, then name
    cards = baker.make("shop.Category", title="Cards", sort_order=-2)
    notebooks = baker.make("shop.Category", title="Notebooks", sort_order=-1)
    baker.make("shop.Product", category=notebooks, name="Notebook", sort_order=1)
    baker.make("shop.Product", category=cards, name="Card B", sort_order=2)
    baker.make("shop.Product", category=cards, name="Calendar", sort_order=5)
    baker.make("shop.Product", category=cards, name="Card A", sort_order=2)
    resp = admin_client.get(reverse("wagtailsnippets_shop_product:list"))
    assert [p.name for p in resp.context["object_list"]] == [
        "Card A",
        "Card B",
        "Calendar",
        "Notebook",
        "Test Product",
    ]
    assert "Sort item order" not in resp.content.decode()


def test_product_breadcrumb_links(admin_client, product):
    variant = baker.make("shop.ProductVariant", product=product, variant_name="Small")
    content = admin_client.get(
        reverse("wagtailsnippets_shop_productvariant:edit", args=(variant.pk,))
    ).content.decode()
    products_url = reverse("wagtailsnippets_shop_product:list")
    # the category's products, and the product's page
    assert f'href="{products_url}?category={product.category.pk}"' in content
    assert f'href="{reverse("wagtailsnippets_shop_product:edit", args=(product.pk,))}"' in content
