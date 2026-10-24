"""
Categories: plain models (not Wagtail pages), with pages served by the shop page,
managed in the Shop admin, and created from a product's category chooser.
"""

import html
import json

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from model_bakery import baker
from wagtail.models import Site

from ..models import Category, reserved_category_slugs
from .factories import ShopPageFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    yield client


@pytest.fixture
def served_shop_page(home_page):
    # Serve the home page from the default site, so pages can be requested
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    yield ShopPageFactory(parent=home_page, title="Shop", slug="shop")


def full_clean(category):
    category.full_clean()
    return category


# The model


def test_category(category):
    assert str(category) == "Test Category"
    assert category.get_product_count() == "0 live (0 total)"
    assert list(category.live_products) == []


def test_new_category_slug_and_order():
    first = Category.objects.create(title="Mugs & Gifts")
    second = Category.objects.create(title="Cards")
    assert first.slug == "mugs-gifts"
    # new categories go last
    assert (first.sort_order, second.sort_order) == (0, 1)
    assert list(Category.objects.all()) == [first, second]


def test_category_slug_from_title(category):
    new = full_clean(Category(title="Calendars & Cards"))
    assert new.slug == "calendars-cards"


@pytest.mark.parametrize("title", ["Test Category", "test category"])
def test_category_title_unique(category, title):
    with pytest.raises(ValidationError) as error:
        full_clean(Category(title=title, slug="other"))
    assert error.value.message_dict == {
        "title": [f"There's already a category called '{title}'."]
    }


def test_category_keeps_its_own_title_and_slug(category):
    full_clean(category)


def test_category_slug_unique(category):
    # a slug given, or made from the title
    with pytest.raises(ValidationError) as error:
        full_clean(Category(title="Mugs", slug="test-category"))
    assert "slug" in error.value.message_dict
    with pytest.raises(ValidationError) as error:
        full_clean(Category(title="Test category!"))
    assert error.value.message_dict["title"] == [
        "Another category already has the web address 'test-category'."
    ]


def test_category_reserved_slugs(served_shop_page):
    # the shop's own pages, and the shop page's child pages
    served_shop_page.add_child(instance=ShopPageFactory.build(title="About", slug="about"))
    reserved = reserved_category_slugs()
    assert {"basket", "checkout", "product", "order", "about"} <= reserved
    with pytest.raises(ValidationError) as error:
        full_clean(Category(title="Mugs", slug="basket"))
    assert error.value.message_dict == {
        "slug": ["The web address 'basket' is used by another shop page."]
    }
    with pytest.raises(ValidationError) as error:
        full_clean(Category(title="About"))
    assert error.value.message_dict == {
        "title": ["The web address 'about' is used by another shop page."]
    }


def test_reserved_slugs_no_shop_page():
    assert "basket" in reserved_category_slugs()


def test_category_title_case_insensitive_constraint(category):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(title="TEST CATEGORY", slug="other")


def test_category_url(served_shop_page, category):
    # (with the host, as the tests have more than one site)
    assert category.url.endswith("/shop/test-category/")
    assert category.get_absolute_url() == category.url
    assert category.url_display() == f'<a href="{category.url}">{category.url}</a>'
    assert category.get_url(None) == category.url


def test_category_url_no_shop_page():
    category = Category.objects.create(title="Mugs")
    assert category.url is None
    assert category.url_display() == "-"


# Category pages, served by the shop page


@pytest.fixture
def mugs(served_shop_page):
    category = Category.objects.create(
        title="Mugs & Gifts", description="<p>Lovely mugs</p>"
    )
    product = baker.make("shop.Product", name="Podenco mug", category=category, price=10)
    baker.make("shop.ProductVariant", product=product, stock=5)
    yield category


def test_category_page(client, mugs):
    resp = client.get("/shop/mugs-gifts/")
    assert resp.status_code == 200
    content = html.unescape(resp.content.decode())
    assert "<title>" in content and "Mugs & Gifts" in content.split("</title>")[0]
    assert "Lovely mugs" in content
    assert "Podenco mug" in content
    # breadcrumbs: Home > Shop > Mugs & Gifts
    assert '<a href="/shop/">Shop</a>' in content
    assert '<li aria-current="page">Mugs & Gifts</li>' in content


def test_category_page_empty(client, served_shop_page):
    Category.objects.create(title="Cards")
    content = html.unescape(client.get("/shop/cards/").content.decode())
    assert "There's nothing in this category at the moment." in content


def test_category_page_not_found(client, served_shop_page):
    assert client.get("/shop/no-such-category/").status_code == 404


def test_shop_page_links_to_categories(client, mugs):
    # (only categories with live products are shown)
    Category.objects.create(title="Empty")
    content = html.unescape(client.get("/shop/").content.decode())
    assert f'<a href="{mugs.url}">Mugs & Gifts</a>' in content
    assert "/shop/empty/" not in content


def test_product_page_breadcrumbs(client, mugs):
    product = mugs.products.get()
    content = html.unescape(
        client.get(reverse("shop:product_detail", args=(product.id,))).content.decode()
    )
    assert '<a href="/shop/mugs-gifts/">Mugs & Gifts</a>' in content
    assert '<li aria-current="page">Podenco mug</li>' in content


# The admin


def test_categories_list(admin_client, served_shop_page, product):
    other = Category.objects.create(title="Cards")
    resp = admin_client.get(reverse("wagtailsnippets_shop_category:list"))
    assert list(resp.context["object_list"]) == [product.category, other]
    content = resp.content.decode()
    assert "0 live (1 total)" in content
    assert "/shop/cards/" in content
    # categories are dragged into their order on the shop page
    assert "Sort item order" in content


def test_reorder_categories(admin_client, category):
    cards = Category.objects.create(title="Cards")
    url = reverse("wagtailsnippets_shop_category:reorder", args=(cards.pk,))
    admin_client.post(f"{url}?position=0")
    assert list(Category.objects.all()) == [cards, category]


def test_add_category_in_admin(admin_client, served_shop_page):
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_category:add"),
        {"title": "Mugs & Gifts", "slug": "", "description": json.dumps({"blocks": [], "entityMap": {}})},
    )
    assert resp.status_code == 302
    category = Category.objects.get()
    assert category.slug == "mugs-gifts"


def test_create_category_from_chooser(admin_client, served_shop_page):
    # e.g. from a product's category field
    chooser_url = reverse("wagtailsnippetchoosers_shop_category:choose")
    resp = admin_client.get(chooser_url)
    assert "Add a category" in resp.content.decode()
    resp = admin_client.post(
        reverse("wagtailsnippetchoosers_shop_category:create"),
        {"title": "Mugs"},
    )
    data = resp.json()
    assert data["step"] == "chosen"
    category = Category.objects.get()
    assert data["result"]["id"] == str(category.pk)
    assert category.slug == "mugs"


def test_create_category_from_chooser_duplicate(admin_client, category):
    resp = admin_client.post(
        reverse("wagtailsnippetchoosers_shop_category:create"),
        {"title": "test category"},
    )
    data = resp.json()
    assert data["step"] == "reshow_creation_form"
    assert "There&#x27;s already a category called" in data["htmlFragment"]
    assert Category.objects.count() == 1


def test_product_form_category_chooser(admin_client, product):
    content = admin_client.get(
        reverse("wagtailsnippets_shop_product:edit", args=(product.pk,))
    ).content.decode()
    assert reverse("wagtailsnippetchoosers_shop_category:choose") in content


def test_category_no_title():
    # (the title's own "required" error is enough)
    with pytest.raises(ValidationError) as error:
        full_clean(Category(title=""))
    assert list(error.value.message_dict) == ["title"]
