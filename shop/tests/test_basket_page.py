"""The basket and checkout pages' layout: item rows, the summary and links"""

import html

import pytest
import wagtail_factories
from django.urls import reverse
from django.contrib.auth.models import AnonymousUser
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


# The quantity buttons' limits (quantity_buttons.js disables + at the max)


def test_basket_quantity_max(basket_client, basket):
    # 2 in the basket, 5 more available: up to 7
    variant = basket.get_items()[0].product
    resp = basket_client.get(reverse("shop:basket"))
    (item,) = resp.context["basket"]["items"][variant.product.identifier]
    assert item["max_quantity"] == variant.available + 2
    assert f'value="2" max="{variant.available + 2}"' in resp.content.decode()
    # changing the quantity in the basket keeps the max
    for view in ["decrease_quantity", "increase_quantity"]:
        content = basket_client.get(
            reverse(f"shop:{view}", args=(variant.product.id,)),
            {"variant_id": variant.id, "quantity": 2, "ref": "basket"},
        ).content.decode()
        assert f'max="{variant.available + 2}"' in content


def test_shop_quantity_no_max(client, basket):
    # on the shop and product pages, the variant gives the max (its
    # data-available), as it can change with the variant chosen
    variant = basket.get_items()[0].product
    content = client.get(
        reverse("shop:increase_quantity", args=(variant.product.id,)),
        {"variant_id": variant.id, "quantity": 1},
    ).content.decode()
    assert "max=" not in content
    content = client.get(reverse("shop:product_detail", args=(variant.product.id,))).content.decode()
    assert f'value="{variant.id}" data-available="{variant.available}"' in content


def test_none_available(client, basket):
    variant = basket.get_items()[0].product
    variant.stock = 0
    variant.save()
    content = client.get(
        reverse("shop:increase_quantity", args=(variant.product.id,)),
        {"variant_id": variant.id, "quantity": 1},
    ).content.decode()
    assert "class='alert-danger' hx-swap-oob='true'>None available</div>" in content


def test_refused_quantity_max(client, basket):
    # stock has changed since the page loaded: the field gets the real max
    variant = basket.get_items()[0].product
    variant.stock = 1
    variant.save()
    content = client.get(
        reverse("shop:increase_quantity", args=(variant.product.id,)),
        {"variant_id": variant.id, "quantity": 1},
    ).content.decode()
    assert 'value="1" max="1"' in content
    assert "Only 1 available</div>" in content


def test_decrease_quantity_unknown_variant_in_basket(client, basket):
    # (e.g. deleted): the quantity still changes, with no max
    product = basket.get_items()[0].product.product
    content = client.get(
        reverse("shop:decrease_quantity", args=(product.id,)),
        {"variant_id": 99999, "quantity": 3, "ref": "basket"},
    ).content.decode()
    assert 'value="2">' in content
    assert "max=" not in content


def increase(client, variant, quantity, **params):
    return " ".join(
        client.get(
            reverse("shop:increase_quantity", args=(variant.product.id,)),
            {"variant_id": variant.id, "quantity": quantity, **params},
        ).content.decode().split()
    )


def test_refused_updates_variant_options(client, product):
    # stock taken since the page loaded: the options show the real stock,
    # keeping the chosen variant
    small = baker.make("shop.ProductVariant", product=product, variant_name="Small", stock=10)
    large = baker.make("shop.ProductVariant", product=product, variant_name="Large", stock=1)
    content = increase(client, large, 1)
    assert "Only 1 available</div>" in content
    assert f"<div id='id_select_variant_wrapper_{product.id}' hx-swap-oob='true'>" in content
    assert f'<option value="{large.id}" data-available="1" data-in-basket="0" data-name="Large" selected> Large (only 1 left) </option>' in content
    assert f'<option value="{small.id}" data-available="10" data-in-basket="0" data-name="Small">' in content
    # still in stock: the buttons stay
    assert f"<div id='change_quantity_wrapper_{product.id}' hx-swap-oob='true'></div>" not in content


def test_refused_single_variant_note(client, basket):
    variant = basket.get_items()[0].product
    variant.stock = 1
    variant.save()
    content = increase(client, variant, 1)
    assert '<p class="shop-card__stock">Only 1 left</p>' in content


def test_refused_now_out_of_stock(client, basket):
    # none left: "Out of stock", without the quantity and add buttons
    variant = basket.get_items()[0].product
    variant.stock = 0
    variant.save()
    content = increase(client, variant, 1)
    assert "Out of stock</p>" in content
    assert f"<div id='change_quantity_wrapper_{variant.product.id}' hx-swap-oob='true'></div>" in content


def test_refused_in_basket_no_variant_options(basket_client, basket):
    variant = basket.get_items()[0].product
    content = increase(basket_client, variant, 2 + variant.available, ref="basket")
    assert "available</div>" in content
    assert "id_select_variant_wrapper" not in content


def test_add_refused_now_out_of_stock(client, product):
    # e.g. the last ones were added in another tab: "None available", "Out of
    # stock", and no quantity or add buttons
    small = baker.make("shop.ProductVariant", product=product, variant_name="Small", stock=0)
    content = " ".join(
        client.post(
            reverse("shop:add_to_basket", args=(product.id,)),
            {"variant_id": small.id, "quantity": 2},
        ).content.decode().split()
    )
    assert "None available</div>" in content
    assert "Out of stock</p>" in content
    assert f"<div id='change_quantity_wrapper_{product.id}' hx-swap-oob='true'></div>" in content
    assert "id_quantity_wrapper" not in content


def test_added_variant_stays_selected(client, product):
    small = baker.make("shop.ProductVariant", product=product, variant_name="Small", stock=10)
    large = baker.make("shop.ProductVariant", product=product, variant_name="Large", stock=3)

    def add(variant, quantity):
        return " ".join(
            client.post(
                reverse("shop:add_to_basket", args=(product.id,)),
                {"variant_id": variant.id, "quantity": quantity},
            ).content.decode().split()
        )

    content = add(large, 1)
    assert "Added!" in content
    # (with how many are in the basket, for "1 in your basket")
    assert f'<option value="{large.id}" data-available="2" data-in-basket="1" data-name="Large" selected>' in content
    # the last ones: their option is disabled, so it isn't kept selected
    content = add(large, 2)
    assert f'<option value="{large.id}" data-available="0" data-in-basket="3" data-name="Large" disabled>' in content
    assert " selected" not in content.split("id_select_variant_wrapper")[1].split("</select>")[0]
    assert f'<option value="{small.id}" data-available="10" data-in-basket="0" data-name="Small">' in content


# "N in your basket", by the product's form


def test_in_basket_tag(rf, basket):
    from django.template import Context, Template

    variant = basket.get_items()[0].product
    other = baker.make("shop.ProductVariant", product=variant.product, stock=5)
    template = Template("{% load shoptags %}{% in_basket variant %}")
    request = rf.get("/")
    request.session = {"BASKET_ID": basket.id}
    request.user = AnonymousUser()
    assert template.render(Context({"request": request, "variant": variant})) == "2"
    assert template.render(Context({"request": request, "variant": other})) == "0"
    # no basket, or no request
    request = rf.get("/")
    request.session = {}
    request.user = AnonymousUser()
    assert template.render(Context({"request": request, "variant": variant})) == "0"
    assert template.render(Context({"variant": variant})) == "0"


def test_in_basket_on_product_page(basket_client, basket):
    variant = basket.get_items()[0].product
    content = get(basket_client, reverse("shop:product_detail", args=(variant.product.id,)))
    assert f'data-available="{variant.available}" data-in-basket="2"' in content
    # (filled in by quantity_buttons.js)
    assert f'<p class="shop-in-basket" hidden><a href="{reverse("shop:basket")}"></a></p>' in content


def test_in_basket_when_out_of_stock(basket_client, basket):
    # out of stock (e.g. the last ones are in the basket): no options, but still
    # what's in the basket, for "In your basket: Small × 2"
    variant = basket.get_items()[0].product
    baker.make("shop.ProductVariant", product=variant.product, variant_name="Large", stock=0)
    variant.stock = 0
    variant.save()
    content = get(basket_client, reverse("shop:product_detail", args=(variant.product.id,)))
    assert "Out of stock" in content
    assert 'name="variant_id"' not in content
    assert '<input type="hidden" data-in-basket="2" data-name="Small">' in content
    assert '<input type="hidden" data-in-basket="0" data-name="Large">' in content


# The order status page


@pytest.fixture
def paid_order(order):
    order.status = order.Status.PROCESSING
    order.save()
    order.pay(amount=order.total, transaction_id="pi_1", payment_method="stripe")
    return order


@pytest.mark.parametrize(
    "shipping_status,shipping_method,label",
    [
        ("to_send", "deliver", "To be sent"),
        ("to_send", "collect", "To be collected"),
        ("shipped", "deliver", "Shipped"),
        ("shipped", "collect", "Collected"),
        ("not_sent", "deliver", "Won't be sent"),
        ("no_shipping", "deliver", None),
    ],
)
def test_order_status_item_status(client, paid_order, shipping_status, shipping_method, label):
    paid_order.shipping_method = shipping_method
    paid_order.save()
    paid_order.items.update(shipping_status=shipping_status)
    resp = client.get(reverse("shop:order_status", args=(paid_order.token,)))
    (item,) = resp.context["items"]
    assert item["status"] == label
    if label:
        assert f'<span class="basket-item__status">{label}</span>' in html.unescape(resp.content.decode())


def test_order_status_page(client, paid_order):
    content = get(client, reverse("shop:order_status", args=(paid_order.token,)))
    assert ">Go to shop</a>" in content
    assert "Continue shopping" not in content
    # the basket link isn't shown
    assert "shop-basket-link" not in content


def test_in_basket_variant_names(basket_client, basket):
    # each option has its short name, for "In your basket: Small × 2" whichever
    # variant is selected
    variant = basket.get_items()[0].product
    baker.make("shop.ProductVariant", product=variant.product, variant_name="Large", stock=5)
    content = get(basket_client, reverse("shop:product_detail", args=(variant.product.id,)))
    assert f'value="{variant.id}" data-available="{variant.available}" data-in-basket="2" data-name="Small"' in content
    assert 'data-in-basket="0" data-name="Large"' in content
