"""
The product card is used on the shop page, category pages and the product
page. Check on each page that its htmx buttons refer to their own product's
fields, and that the elements the views update are present exactly once.
"""
import re
from collections import Counter
from html.parser import HTMLParser

import pytest
from model_bakery import baker

from django.urls import reverse
from wagtail.models import Site

from .factories import CategoryPageFactory, ShopPageFactory

pytestmark = pytest.mark.django_db


class CardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = Counter()
        self.htmx_elements = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids[attrs["id"]] += 1
        if any(key in attrs for key in ["hx-get", "hx-post"]):
            self.htmx_elements.append(attrs)


@pytest.fixture
def shop_pages(home_page):
    # Serve the home page from the default site, so pages can be requested
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    shop_page = ShopPageFactory(parent=home_page, title="Shop", slug="shop")
    category_page = CategoryPageFactory(
        parent=shop_page, title="Category", slug="category"
    )
    products = []
    for name in ["Mug", "T-shirt"]:
        product = baker.make("shop.Product", name=name, category_page=category_page)
        baker.make("shop.ProductVariant", product=product, price=10, stock=5)
        products.append(product)
    yield products


def get_page(client, page, products):
    if page == "shop":
        url = "/shop/"
    elif page == "category":
        url = "/shop/category/"
    else:
        url = reverse("shop:product_detail", args=(products[0].id,))
    resp = client.get(url)
    assert resp.status_code == 200
    parser = CardParser()
    parser.feed(resp.content.decode())
    return parser


@pytest.mark.parametrize("page", ["shop", "category", "product"])
def test_product_cards(client, shop_pages, page):
    parser = get_page(client, page, shop_pages)
    products = shop_pages if page != "product" else shop_pages[:1]

    for product in products:
        # elements targeted by the views (including out-of-band swaps) and by
        # hx-include are on the page exactly once
        for element_id in [
            f"id_product_{product.id}",
            f"id_quantity_{product.id}",
            f"id_quantity_wrapper_{product.id}",
            f"id_select_variant_wrapper_{product.id}",
            f"change_quantity_wrapper_{product.id}",
            f"added_{product.id}",
        ]:
            assert parser.ids[element_id] == 1, element_id

        # the -/+ buttons include this product's fields only
        for view in ["decrease_quantity", "increase_quantity"]:
            url = reverse(f"shop:{view}", args=(product.id,))
            (button,) = [el for el in parser.htmx_elements if el.get("hx-get") == url]
            assert button["hx-target"] == f"#id_quantity_wrapper_{product.id}"
            included_ids = re.findall(r"\[id='([^']+)'\]", button["hx-include"])
            assert included_ids == [f"id_quantity_{product.id}", f"id_product_{product.id}"]

        # add to basket posts the card's form, which contains the product's fields
        add_url = reverse("shop:add_to_basket", args=(product.id,))
        (add_button,) = [
            el for el in parser.htmx_elements if el.get("hx-post") == add_url
        ]
        assert add_button["hx-target"] == "#basket-icon"

    # the basket icon targeted by add to basket is on the page once
    assert parser.ids["basket-icon"] == 1
