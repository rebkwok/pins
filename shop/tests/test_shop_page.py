"""
The shop page's product cards (prices, stock notes), its search and its category
buttons.
"""

import html
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import RequestFactory
from django.template import Context, Template
from django.utils import timezone
from model_bakery import baker
from wagtail.models import Site

from ..models import Category, Product, ProductVariant
from .factories import ShopPageFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(home_page):
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    page = ShopPageFactory(parent=home_page, title="Shop", slug="shop")
    mugs = Category.objects.create(title="Mugs", slug="mugs")
    clothing = Category.objects.create(title="Clothing", slug="clothing")
    products = {}
    for category, name, prices, stock, description in [
        (mugs, "Podenco mug", [10], 20, "<p>A big mug</p>"),
        (mugs, "Small cup", [6], 0, ""),
        (clothing, "T-shirt", [18, 18], 3, "<p>Organic cotton</p>"),
        (clothing, "Hoodie", [30, 35], 10, ""),
    ]:
        product = Product.objects.create(
            category=category, name=name, price=prices[0], description=description
        )
        for index, price in enumerate(prices):
            ProductVariant.objects.create(
                product=product, variant_name=f"Option {index}", price=price, stock=stock
            )
        products[name] = product
    return page, products


def names(resp):
    return [product.name for product in resp.context["products"]]


# Prices and stock


def test_price_summary(shop):
    page, products = shop
    mug = products["Podenco mug"].price_summary
    assert (mug.price, mug.was, mug.varies) == (Decimal("10"), None, False)
    hoodie = products["Hoodie"].price_summary
    assert (hoodie.price, hoodie.varies) == (Decimal("30"), True)
    # no live variants
    products["Podenco mug"].variants.update(live=False)
    assert Product.objects.get(name="Podenco mug").price_summary is None


def test_price_summary_sale(shop):
    page, products = shop
    sale = baker.make(
        "shop.Sale",
        name="Sale",
        start_date=timezone.now() - timedelta(days=1),
        end_date=timezone.now() + timedelta(days=1),
    )
    baker.make("shop.SaleProduct", sale=sale, product=products["Podenco mug"], discount=10)
    mug = Product.objects.get(name="Podenco mug")
    assert (mug.price_summary.price, mug.price_summary.was) == (Decimal("9.00"), Decimal("10"))
    assert Product.objects.get(name="Hoodie").price_summary.was is None


@pytest.mark.parametrize("stock,note", [(0, "Out of stock"), (3, "Only 3 left"), (5, "Only 5 left"), (6, "")])
def test_stock_note(shop, stock, note):
    page, products = shop
    variant = products["Podenco mug"].variants.get()
    variant.stock = stock
    assert variant.stock_note() == note


def test_cards(client, shop):
    page, products = shop
    content = " ".join(html.unescape(client.get("/shop/").content.decode()).split())
    # names, prices ("From" when they differ), and low stock
    assert ">Podenco mug</a>" in content
    assert "From <strong>£30.00</strong>" in content
    assert "> Option 0 (only 3 left) </option>" in content
    assert "Out of stock" in content
    # products with options link to their page to choose them (on phones)
    assert "Choose options" in content


# Search and categories


def test_grouped_by_category(client, shop):
    page, products = shop
    resp = client.get("/shop/")
    groups = resp.context["product_groups"]
    assert [(category.title, [p.name for p in group]) for category, group in groups] == [
        ("Mugs", ["Podenco mug", "Small cup"]),
        ("Clothing", ["T-shirt", "Hoodie"]),
    ]
    assert [c.title for c in resp.context["filter_categories"]] == ["Mugs", "Clothing"]


@pytest.mark.parametrize(
    "query,expected",
    [
        # (the category "Mugs" matches too)
        ("mug", ["Podenco mug", "Small cup"]),
        ("podenco", ["Podenco mug"]),
        ("COTTON", ["T-shirt"]),
        ("clothing", ["T-shirt", "Hoodie"]),
        ("nothing", []),
    ],
)
def test_search(client, shop, query, expected):
    resp = client.get("/shop/", {"q": query})
    assert names(resp) == expected


def test_no_matches(client, shop):
    content = html.unescape(client.get("/shop/", {"q": "nothing"}).content.decode())
    assert "No products match." in content
    assert '<a href="?">Clear the search</a>' in content


def test_category(client, shop):
    resp = client.get("/shop/", {"category": "clothing"})
    assert names(resp) == ["T-shirt", "Hoodie"]
    assert resp.context["category"].title == "Clothing"
    # a search within the category
    assert names(client.get("/shop/", {"category": "clothing", "q": "cotton"})) == ["T-shirt"]
    # an unknown category: nothing
    resp = client.get("/shop/", {"category": "nope"})
    assert names(resp) == []
    assert resp.context["category"] is None


def test_results_summary(client, shop):
    # with a search: what's shown, and a way to clear it (keeping the category)
    assert "Clear the search" not in client.get("/shop/").content.decode()
    assert "Clear the search" not in client.get("/shop/", {"category": "mugs"}).content.decode()
    content = " ".join(html.unescape(client.get("/shop/", {"q": "o"}).content.decode()).split())
    # (not "Small cup")
    assert '3 of 4 products shown. <a href="?">Clear the search</a>' in content
    content = html.unescape(client.get("/shop/", {"q": "o", "category": "mugs"}).content.decode())
    assert '<a href="?category=mugs">Clear the search</a>' in content


def test_category_buttons_keep_search(client, shop):
    content = html.unescape(client.get("/shop/", {"q": "o", "category": "mugs"}).content.decode())
    assert re.search(r'href="\?q=o&category=clothing"[^>]*>Clothing', content)
    assert re.search(r'href="\?q=o"[^>]*>All', content)
    assert 'href="?q=o&category=mugs" aria-current="true"' in content


def test_shop_filter_url():
    template = Template("{% load shoptags %}{% shop_filter_url category='' %}")
    request = RequestFactory().get("/shop/", {"category": "mugs"})
    assert template.render(Context({"request": request})) == "?"


def test_no_photo(client, shop):
    # (the products have no images)
    page, products = shop
    content = client.get("/shop/").content.decode()
    assert content.count("No photo available") == 4
    url = f"/shop/product/{products['Hoodie'].id}/"
    assert "No photo available" in client.get(url).content.decode()
