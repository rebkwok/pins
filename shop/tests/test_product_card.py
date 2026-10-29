"""
The product card is used on the shop page (all categories, or one) and the
product page. Check on each page that its htmx buttons refer to their own product's
fields, and that the elements the views update are present exactly once.
"""
import re
from collections import Counter
from datetime import datetime, UTC
from html.parser import HTMLParser

import pytest
from model_bakery import baker

from django.urls import reverse
import wagtail_factories
from wagtail.models import Site

from ..models import Sale, SaleProduct
from .factories import ShopPageFactory

pytestmark = pytest.mark.django_db


class CardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = Counter()
        self.htmx_elements = []
        self.carousels = []
        self.indicators = []
        self.image_links = []
        self.attr_names = set()
        self.link_depth = 0
        self.nested_links = 0
        self.indicators_in_links = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.attr_names.update(attrs)
        if "id" in attrs:
            self.ids[attrs["id"]] += 1
        if any(key in attrs for key in ["hx-get", "hx-post"]):
            self.htmx_elements.append(attrs)
        if "carousel" in attrs.get("class", "").split():
            self.carousels.append(attrs)
        if "data-bs-slide-to" in attrs:
            self.indicators.append(attrs)
            if self.link_depth:
                self.indicators_in_links += 1
        if tag == "a":
            if self.link_depth:
                self.nested_links += 1
            self.link_depth += 1
            self.image_links.append(attrs.get("href"))

    def handle_endtag(self, tag):
        if tag == "a" and self.link_depth:
            self.link_depth -= 1


@pytest.fixture
def shop_pages(home_page):
    # Serve the home page from the default site, so pages can be requested
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    shop_page = ShopPageFactory(parent=home_page, title="Shop", slug="shop")
    category = baker.make("shop.Category", title="Category", slug="category")
    products = []
    for name in ["Mug", "T-shirt"]:
        product = baker.make("shop.Product", name=name, category=category)
        baker.make("shop.ProductVariant", product=product, price=10, stock=5)
        products.append(product)
    yield products


def get_page(client, page, products):
    if page == "shop":
        url = "/shop/"
    elif page == "category":
        url = "/shop/?category=category"
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
            f"id_variant_{product.id}",
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
            assert included_ids == [f"id_quantity_{product.id}", f"id_variant_{product.id}"]

        # add to basket posts the card's form, which contains the product's fields
        add_url = reverse("shop:add_to_basket", args=(product.id,))
        (add_button,) = [
            el for el in parser.htmx_elements if el.get("hx-post") == add_url
        ]
        assert add_button["hx-target"] == "#basket-icon"

    # the basket icon targeted by add to basket is on the page once
    assert parser.ids["basket-icon"] == 1


# Image carousel


def add_images(product, count):
    baker.make("shop.ProductImage", product=product, image=wagtail_factories.ImageFactory())
    for i in range(count - 1):
        baker.make(
            "shop.ProductVariant",
            product=product,
            variant_name=f"Variant {i}",
            image=wagtail_factories.ImageFactory(),
            stock=1,
        )


@pytest.mark.parametrize("page", ["shop", "category"])
def test_product_cards_first_image(client, shop_pages, page):
    # listing pages: each product's first image, linking to its page (no
    # carousels)
    for product in shop_pages:
        add_images(product, 2)
    parser = get_page(client, page, shop_pages)
    assert parser.carousels == []
    assert parser.indicators == []
    for product in shop_pages:
        detail_url = reverse("shop:product_detail", args=(product.id,))
        # (the image, the name, and "Choose options", for products with a
        # choice of options)
        assert parser.image_links.count(detail_url) == 3
    assert parser.nested_links == 0


def test_product_page_carousel(client, shop_pages):
    product = shop_pages[0]
    add_images(product, 2)
    parser = get_page(client, "product", shop_pages)
    # one carousel, using Bootstrap 5 attributes
    (carousel,) = parser.carousels
    assert carousel["id"] == f"shop-carousel-{product.id}"
    assert carousel["data-bs-ride"] == "carousel"
    assert "shop-carousel--detail" in carousel["class"]
    assert not parser.attr_names & {"data-ride", "data-target", "data-slide-to"}
    assert [
        (indicator["data-bs-target"], indicator["data-bs-slide-to"])
        for indicator in parser.indicators
    ] == [(f"#shop-carousel-{product.id}", "0"), (f"#shop-carousel-{product.id}", "1")]
    # images link to the image files; indicators aren't inside links
    for image in product.images:
        assert parser.image_links.count(image.image.file.url) == 1
    assert parser.indicators_in_links == 0
    assert parser.nested_links == 0


def test_product_page_single_image(client, shop_pages):
    add_images(shop_pages[0], 1)
    parser = get_page(client, "product", shop_pages)
    (carousel,) = parser.carousels
    # no indicators or auto-play for a single image
    assert "data-bs-ride" not in carousel
    assert parser.indicators == []


def test_product_card_alt_text(client, shop_pages):
    product = shop_pages[0]
    image = wagtail_factories.ImageFactory(title="Mug photo")
    baker.make("shop.ProductImage", product=product, image=image, alt_text="Mug front")
    baker.make(
        "shop.ProductImage", product=product, image=wagtail_factories.ImageFactory(title="Side")
    )
    content = client.get(reverse("shop:product_detail", args=(product.id,))).content.decode()
    assert 'alt="Mug front"' in content
    # an image without alt text uses its title
    assert 'alt="Side"' in content
    # the alt text isn't shown as a caption
    assert ">Mug front<" not in content
    # on listing pages, the image is decorative: the product's name follows it
    content = client.get("/shop/?category=category").content.decode()
    assert 'alt="Mug front"' not in content
    assert '<a href="/shop/product/' in content


# Sale banner


def test_sale_banner_shown_during_sale(client, shop_pages, freezer):
    freezer.move_to("2024-06-01 10:00")
    sale = Sale.objects.create(
        name="Summer sale",
        banner_title="Summer sale!",
        banner_content="20% off mugs",
        banner_include_end=True,
        start_date=datetime(2024, 5, 1, tzinfo=UTC),
        end_date=datetime(2024, 7, 1, 12, 30, tzinfo=UTC),
    )
    SaleProduct.objects.create(sale=sale, product=shop_pages[0], discount=20)

    for url in ["/shop/", "/shop/?category=category", reverse("shop:product_detail", args=(shop_pages[0].id,))]:
        content = client.get(url).content.decode()
        assert "Summer sale!" in content, url
        assert "20% off mugs" in content
        assert "Sale ends on 01 Jul 2024 at 12:30" in content


def test_no_sale_banner_without_sale(client, shop_pages):
    content = client.get("/shop/").content.decode()
    assert "Sale ends on" not in content
    assert "jumbotron" not in content


# Product page layout


def test_product_page_columns_stack_on_phones(client, shop_pages):
    product = shop_pages[0]
    product.description = "<p>A lovely mug</p>"
    product.save()
    content = client.get(reverse("shop:product_detail", args=(product.id,))).content.decode()
    # full width on phones, side by side from tablet width
    assert content.count('<div class="col-12 col-md-6">') == 2


def test_basket_icon_in_navigation(client, shop_pages):
    content = client.get("/shop/").content.decode()
    navigation = content[content.index('<div class="navigation" data-navigation>'):]
    navigation = navigation[: navigation.index('<div class="breadcrumb')] if '<div class="breadcrumb' in navigation else navigation
    assert '<div id="basket-icon" class="navigation__basket">' in navigation
    assert 'aria-label="Basket (0 items)"' in content


def test_no_basket_icon_on_other_pages(client, home_page):
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    content = client.get("/").content.decode()
    assert "navigation__basket" not in content
