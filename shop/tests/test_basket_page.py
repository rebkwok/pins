"""The basket and checkout pages' layout: item rows, the summary and links"""

import html

import pytest
import wagtail_factories
from django.urls import reverse
from model_bakery import baker
from ..forms import MainButton

pytestmark = pytest.mark.django_db

CHECKOUT_URL = reverse("shop:checkout") + "?payment-method=stripe&shipping-method=deliver"


@pytest.fixture
def basket_client(client, basket):
    session = client.session
    session["BASKET_ID"] = basket.id
    session.save()
    return client


def get(client, url):
    return " ".join(html.unescape(client.get(url).content.decode()).split())


def test_basket_item(basket_client, basket):
    variant = basket.get_items()[0].product
    content = get(basket_client, reverse("shop:basket"))
    # one row: the product's name, its variant, the price and controls (no
    # heading per product)
    assert f'<div id="row-{variant.id}" class="basket-item basket-item--editable">' in content
    assert f"<strong>{variant.product.name}</strong>" in content
    assert '<span class="basket-item__variant">Small</span>' in content
    assert f'aria-label="Remove {variant.name}"' in content
    assert "<h2>" not in content.split("basket-layout")[1]
    # no image: the logo
    assert "basket-item__placeholder" in content


def test_basket_item_thumbnail(basket_client, basket):
    variant = basket.get_items()[0].product
    # the product's image, or the variant's own
    baker.make("shop.ProductImage", product=variant.product, image=wagtail_factories.ImageFactory(title="Mug"))
    content = get(basket_client, reverse("shop:basket"))
    assert "fill-120x120-c100" in content
    assert "basket-item__placeholder" not in content
    variant.image = wagtail_factories.ImageFactory(title="Small mug")
    variant.save()
    resp = basket_client.get(reverse("shop:basket"))
    (item,) = resp.context["basket"]["items"][variant.product.identifier]
    assert item["image"] == variant.image
    assert item["variant_name"] == "Small"


def test_continue_shopping(basket_client, shop_page):
    # back to the shop page
    content = get(basket_client, reverse("shop:basket"))
    # (relative to the request's site)
    assert f'<a href="/{shop_page.slug}/">Continue shopping</a>' in content


def test_empty_basket(client, shop_page):
    assert "Your basket is empty. <a" in get(client, reverse("shop:basket"))


def test_basket_summary(basket_client):
    content = get(basket_client, reverse("shop:basket"))
    assert '<aside id="basket-summary" class="basket-summary" aria-label="Order summary">' in content
    assert '<p class="basket-line basket-line--total"> <span>Total</span>' in content
    assert '<input class="btn basket-btn shop-main-btn" type="submit" value="Checkout">' in content


def test_checkout_summary(basket_client, basket):
    variant = basket.get_items()[0].product
    content = get(basket_client, CHECKOUT_URL)
    assert f'<a href="{reverse("shop:basket")}">‹ Back to basket</a>' in content
    # the items, without controls
    assert f'<div id="row-{variant.id}" class="basket-item">' in content
    assert f'Quantity: <span id="quantity_{variant.id}">2</span>' in content
    assert "basket-item__controls" not in content
    # Pay now, in the shop's button style
    assert 'class="btn basket-btn shop-main-btn"' in content


def test_main_button():
    assert MainButton("submit", "Pay").field_classes == "btn basket-btn shop-main-btn"


def test_stripe_note(basket_client):
    # paying by card: payment is on Stripe's site (see also test_discounts for
    # a free order)
    note = "Clicking Pay Now takes you to Stripe to complete your payment."
    assert note in get(basket_client, CHECKOUT_URL)
    assert note not in get(basket_client, CHECKOUT_URL.replace("stripe", "pay-in-advance"))
