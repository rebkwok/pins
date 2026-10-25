"""
Categories: plain models (not Wagtail pages), shown on the shop page (all, or one
selected), managed in the Shop admin, and created from a product's category
chooser.
"""

import html
import json

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from model_bakery import baker
from wagtail.models import Site

from ..models import Category
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


def test_category_title_case_insensitive_constraint(category):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(title="TEST CATEGORY", slug="other")


def test_category_url(served_shop_page, category):
    # the shop page with the category selected (with the host, as the tests
    # have more than one site)
    assert category.get_url().endswith("/shop/?category=test-category")
    assert category.shop_link() == f'<a href="{category.get_url()}">View on the shop</a>'


def test_category_url_no_shop_page():
    category = Category.objects.create(title="Mugs")
    assert category.get_url() is None
    assert category.shop_link() == "-"


# A category selected on the shop page


@pytest.fixture
def mugs(served_shop_page):
    category = Category.objects.create(
        title="Mugs & Gifts", description="<p>Lovely mugs</p>"
    )
    product = baker.make("shop.Product", name="Podenco mug", category=category, price=10)
    baker.make("shop.ProductVariant", product=product, stock=5)
    yield category


def test_category_selected(client, mugs):
    content = html.unescape(client.get("/shop/", {"category": "mugs-gifts"}).content.decode())
    assert "Podenco mug" in content
    # the category's description is shown when it's selected
    assert "Lovely mugs" in content
    assert "Lovely mugs" not in html.unescape(client.get("/shop/").content.decode())


def test_category_selected_empty(client, served_shop_page):
    Category.objects.create(title="Cards")
    content = html.unescape(client.get("/shop/", {"category": "cards"}).content.decode())
    assert "There's nothing in this category at the moment." in content


def test_no_category_pages(client, mugs):
    # (categories are selected on the shop page instead)
    assert client.get("/shop/mugs-gifts/").status_code == 404


def test_category_headings(client, mugs):
    # plain headings (not links); only categories with live products have buttons
    other = Category.objects.create(title="Cards")
    product = baker.make("shop.Product", name="Card", category=other, price=2)
    baker.make("shop.ProductVariant", product=product, stock=5)
    Category.objects.create(title="Empty")
    content = html.unescape(client.get("/shop/").content.decode())
    assert '<h2 class="shop-category__title">Mugs & Gifts</h2>' in content
    assert 'href="?category=mugs-gifts"' in content
    assert "?category=empty" not in content


def test_product_page_breadcrumbs(client, mugs):
    # the category links to the shop page with it selected
    product = mugs.products.get()
    content = html.unescape(
        client.get(reverse("shop:product_detail", args=(product.id,))).content.decode()
    )
    assert '<a href="/shop/?category=mugs-gifts">Mugs & Gifts</a>' in content
    assert '<li aria-current="page">Podenco mug</li>' in content


# The admin


def test_categories_list(admin_client, served_shop_page, product):
    other = Category.objects.create(title="Cards")
    resp = admin_client.get(reverse("wagtailsnippets_shop_category:list"))
    assert list(resp.context["object_list"]) == [product.category, other]
    content = resp.content.decode()
    assert "0 live (1 total)" in content
    assert "/shop/?category=cards" in content
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
