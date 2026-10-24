import re
from decimal import Decimal

import pytest
from django.utils.text import slugify
from wagtail.test.utils.form_data import rich_text
from model_bakery import baker

from django.urls import reverse
from salesman.core.utils import get_salesman_model

from ..models import CategoryPage

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
    "model,label,new_label",
    [
        ("product", "Products", "New: Product"),
        ("productvariant", "Product variants", "New: Product variant"),
        ("sale", "Sales", "New: Sale"),
    ],
)
def test_shop_stock_breadcrumbs(
    admin_client, product, sale_with_items, model, label, new_label
):
    instance = {
        "product": product,
        "productvariant": baker.make("shop.ProductVariant", product=product),
        "sale": sale_with_items,
    }[model]
    prefix = f"wagtailsnippets_shop_{model}"
    pages = [
        (reverse(f"{prefix}:list"), []),
        (reverse(f"{prefix}:add"), [new_label]),
        (reverse(f"{prefix}:edit", args=(instance.pk,)), [str(instance)]),
    ]
    for url, last in pages:
        content = admin_client.get(url).content.decode()
        assert breadcrumbs(content) == ["Home", "Shop Stock", label, *last]
        # the menu has no page, so Shop Stock isn't a link
        assert not re.search(r"<a[^>]*>\s*Shop Stock", content)


def test_product_variants_list_order(admin_client, product):
    # products in two categories (product's is "Test Category"), created out of
    # order
    cards = product.category_page.get_parent().add_child(
        instance=CategoryPage(title="Cards", slug="cards")
    )
    mug = baker.make("shop.Product", category_page=product.category_page, name="Mug")
    calendar = baker.make("shop.Product", category_page=cards, name="Calendar")
    baker.make("shop.ProductVariant", product=mug, variant_name="Large", sort_order=2)
    baker.make("shop.ProductVariant", product=product, variant_name="Small", sort_order=1)
    baker.make("shop.ProductVariant", product=calendar, variant_name="Single", sort_order=1)
    baker.make("shop.ProductVariant", product=mug, variant_name="Small", sort_order=1)
    resp = admin_client.get(reverse("wagtailsnippets_shop_productvariant:list"))
    # by category, then product, then the product's variant order
    assert [str(variant) for variant in resp.context["object_list"]] == [
        "Calendar - Single",
        "Mug - Small",
        "Mug - Large",
        "Test Product - Small",
    ]
    # no "Sort item order" for reordering all the variants together
    assert "Sort item order" not in resp.content.decode()


def test_products_list_order(admin_client, product):
    # by category, then the shop page order (index), then name; two categories
    # with the same title aren't mixed together
    shop_page = product.category_page.get_parent()
    cards = shop_page.add_child(instance=CategoryPage(title="Cards", slug="cards"))
    # a duplicate title (allowed in the database, but not in the admin form)
    cards_2 = shop_page.add_child(instance=CategoryPage(title="Cards", slug="cards-2"))
    baker.make("shop.Product", category_page=cards_2, name="Notebook", index=1)
    baker.make("shop.Product", category_page=cards, name="Card B", index=2)
    baker.make("shop.Product", category_page=cards, name="Calendar", index=5)
    baker.make("shop.Product", category_page=cards, name="Card A", index=2)
    resp = admin_client.get(reverse("wagtailsnippets_shop_product:list"))
    assert [p.name for p in resp.context["object_list"]] == [
        "Card A",
        "Card B",
        "Calendar",
        "Notebook",
        "Test Product",
    ]
    assert "Sort item order" not in resp.content.decode()


def category_form(shop_page, title, instance=None):
    form_class = CategoryPage.get_edit_handler().get_form_class()
    data = {
        "title": title,
        "slug": slugify(title) + "-new",
        "body": rich_text(""),
        "index": "1",
        "comments-TOTAL_FORMS": "0",
        "comments-INITIAL_FORMS": "0",
        "comments-MIN_NUM_FORMS": "0",
        "comments-MAX_NUM_FORMS": "1000",
    }
    return form_class(
        data=data,
        instance=instance or CategoryPage(),
        parent_page=shop_page,
        for_user=baker.make("auth.User", is_superuser=True),
    )


@pytest.mark.parametrize("title", ["Test Category", "test category"])
def test_category_title_unique(category_page, title):
    form = category_form(category_page.get_parent(), title)
    assert not form.is_valid()
    assert form.errors["title"] == [
        f"There's already a category called '{title}' in this shop."
    ]


def test_category_title_unique_new_title(category_page):
    assert category_form(category_page.get_parent(), "Clothing").is_valid()


def test_category_title_unique_editing(category_page):
    # a category can keep its own title
    form = category_form(category_page.get_parent(), "Test Category", category_page)
    assert form.is_valid(), form.errors
