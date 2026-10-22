"""
Bad input to the shop views returns a 4xx response, rather than a server error.
"""
import pytest
from model_bakery import baker

from django.contrib.messages import get_messages
from django.template.loader import render_to_string
from django.urls import reverse

from salesman.core.utils import get_salesman_model

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")


@pytest.fixture
def variant(product):
    yield baker.make("shop.ProductVariant", product=product, price=10, stock=5)


@pytest.fixture
def basket_client(client, basket):
    session = client.session
    session["BASKET_ID"] = basket.id
    session.save()
    yield client


def add_data(variant, **params):
    return {
        "product_id": variant.id,
        "product_type": "shop.ProductVariant",
        "quantity": 1,
        **params,
    }


# Product detail


def test_product_detail_not_live(client, product):
    product.live = False
    product.save()
    resp = client.get(reverse("shop:product_detail", args=(product.id,)))
    assert resp.status_code == 404


def test_product_detail_non_numeric_id(client):
    assert client.get("/shop/product/abc/").status_code == 404


# Quantity buttons


@pytest.mark.parametrize(
    "params",
    [
        {"quantity": "abc"},
        {"quantity": "0"},
        {"quantity": "-1"},
        {"product_id": "abc"},
        {"product_id": ""},
    ],
)
def test_decrease_quantity_invalid(client, product, variant, params):
    url = reverse("shop:decrease_quantity", args=(product.id,))
    resp = client.get(url, {"product_id": variant.id, "quantity": 2, **params})
    assert resp.status_code == 400


def test_decrease_quantity_post_not_allowed(client, product):
    url = reverse("shop:decrease_quantity", args=(product.id,))
    assert client.post(url).status_code == 405


@pytest.mark.parametrize(
    "params,status_code",
    [
        ({}, 400),
        ({"product_id": "abc"}, 400),
        # unknown variant in the basket; on the shop page it's shown as unavailable
        ({"product_id": 1234, "ref": "basket"}, 404),
    ],
)
def test_increase_quantity_invalid_variant(client, product, params, status_code):
    url = reverse("shop:increase_quantity", args=(product.id,))
    assert client.get(url, params).status_code == status_code


def test_increase_quantity_invalid_quantity(client, product, variant):
    url = reverse("shop:increase_quantity", args=(product.id,))
    resp = client.get(url, {"product_id": variant.id, "quantity": "abc"})
    assert resp.status_code == 400


# Add to basket


@pytest.mark.parametrize(
    "params",
    [{"product_id": "abc"}, {"quantity": "abc"}, {"quantity": 0}, {"quantity": -1}],
)
def test_add_to_basket_invalid(client, product, variant, params):
    url = reverse("shop:add_to_basket", args=(product.id,))
    resp = client.post(url, add_data(variant, **params))
    assert resp.status_code == 400
    assert not Basket.objects.exists()
    variant.refresh_from_db()
    assert variant.stock == 5


def assert_item_unavailable(resp, product, controls_hidden=True):
    # The product card is updated in place: a message is shown below the
    # product, and the variant options are updated (or removed, along with the
    # quantity and add to basket controls, if none are available)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert (
        f"<div id='added_{product.id}' class='alert-danger mt-2' hx-swap-oob='true'>"
        "Sorry, that item is no longer available.</div>"
    ) in content
    hidden_controls = (
        f"<div id='change_quantity_wrapper_{product.id}' hx-swap-oob='true'></div>"
    )
    assert (hidden_controls in content) == controls_hidden
    return content


def test_add_to_basket_unknown_variant(client, product, variant):
    url = reverse("shop:add_to_basket", args=(product.id,))
    resp = client.post(url, add_data(variant, product_id=1234))
    # the product's other variant is still available
    assert_item_unavailable(resp, product, controls_hidden=False)


@pytest.mark.parametrize("not_live", ["variant", "product"])
def test_add_to_basket_not_live(client, product, variant, not_live):
    # e.g. the item was made not live after the shop page was loaded
    obj = variant if not_live == "variant" else product
    obj.live = False
    obj.save()
    url = reverse("shop:add_to_basket", args=(product.id,))
    resp = client.post(url, add_data(variant))
    content = assert_item_unavailable(resp, product)
    # basket icon is still the main content
    assert "fa-basket-shopping" in content
    variant.refresh_from_db()
    assert variant.stock == 5


def test_add_to_basket_not_live_other_variants_available(client, product, variant):
    other_variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Large", price=10, stock=5
    )
    variant.live = False
    variant.save()
    url = reverse("shop:add_to_basket", args=(product.id,))
    resp = client.post(url, add_data(variant))
    content = assert_item_unavailable(resp, product, controls_hidden=False)
    # variant options are updated
    assert f"<div id='id_select_variant_wrapper_{product.id}' hx-swap-oob='true'>" in content
    assert f'<option value="{other_variant.id}">' in content
    assert f'value="{variant.id}"' not in content


@pytest.mark.parametrize("view", ["increase_quantity", "decrease_quantity"])
@pytest.mark.parametrize("not_live", ["variant", "product"])
def test_change_quantity_not_live(client, product, variant, view, not_live):
    obj = variant if not_live == "variant" else product
    obj.live = False
    obj.save()
    url = reverse(f"shop:{view}", args=(product.id,))
    # On the shop page, the product card is updated and quantity reset to 1
    resp = client.get(url, {"product_id": variant.id, "quantity": 2})
    content = assert_item_unavailable(resp, product)
    assert f'id="id_quantity_{product.id}" name="quantity" type="number" value=1' in content
    # On the basket page, the quantity can still be changed
    resp = client.get(url, {"product_id": variant.id, "quantity": 2, "ref": "basket"})
    assert resp.status_code == 200
    assert "no longer available" not in resp.content.decode()


def test_product_card_buttons_include_own_fields(rf, product, variant):
    # The +/- buttons must send this product's variant and quantity, not those of
    # other products on the page
    other_product = baker.make(
        "shop.Product", name="Other", category_page=product.category_page
    )
    baker.make("shop.ProductVariant", product=other_product, price=10, stock=5)
    html = render_to_string(
        "shop/includes/product-listing-card.html", {"product": product}, rf.get("/")
    )
    assert f'id="id_product_{product.id}"' in html
    include = (
        "hx-include=\"[id='id_quantity_{id}'],[id='id_product_{id}']\""
    ).format(id=product.id)
    assert html.count(include) == 2
    assert "[name='product_id']" not in html


def test_basket_item_not_live_can_be_updated(basket_client, basket):
    # Items already in the basket are honoured; changing quantities keeps
    # stock correct
    item = basket.items.first()
    variant = item.product
    variant.live = False
    variant.save()
    assert variant.stock == 3

    url = reverse("shop:update_quantity", args=(item.ref,))
    resp = basket_client.post(url, {"product_id": variant.id, "quantity": 4})
    assert "Basket updated" in resp.content.decode()
    variant.refresh_from_db()
    assert variant.stock == 1

    url = reverse("shop:delete_basket_item", args=(item.ref,))
    basket_client.post(url, {"product_id": variant.id})
    variant.refresh_from_db()
    assert variant.stock == 5


def test_add_to_basket_get_not_allowed(client, product):
    url = reverse("shop:add_to_basket", args=(product.id,))
    assert client.get(url).status_code == 405


# Update and delete basket items


@pytest.mark.parametrize("quantity", ["abc", "0", ""])
def test_update_quantity_invalid(basket_client, basket, quantity):
    item = basket.items.first()
    url = reverse("shop:update_quantity", args=(item.ref,))
    resp = basket_client.post(url, {"product_id": item.product.id, "quantity": quantity})
    assert resp.status_code == 400
    assert Basket.objects.get(id=basket.id).quantity == 2


def test_update_quantity_unknown_item(basket_client, basket):
    item = basket.items.first()
    url = reverse("shop:update_quantity", args=("unknown-ref",))
    resp = basket_client.post(url, {"product_id": item.product.id, "quantity": 1})
    assert resp.status_code == 404


def test_update_quantity_get_not_allowed(basket_client, basket):
    url = reverse("shop:update_quantity", args=(basket.items.first().ref,))
    assert basket_client.get(url).status_code == 405


@pytest.mark.parametrize(
    "product_id,status_code", [("abc", 400), ("", 400), (1234, 404)]
)
def test_delete_basket_item_invalid(basket_client, basket, product_id, status_code):
    url = reverse("shop:delete_basket_item", args=(basket.items.first().ref,))
    resp = basket_client.post(url, {"product_id": product_id})
    assert resp.status_code == status_code
    assert basket.items.exists()


def test_delete_basket_item_get_not_allowed(basket_client, basket):
    url = reverse("shop:delete_basket_item", args=(basket.items.first().ref,))
    assert basket_client.get(url).status_code == 405


# Checkout


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?shipping-method=collect",
        "?payment-method=stripe",
        "?payment-method=unknown&shipping-method=collect",
        # not enabled in settings
        "?payment-method=pay-in-advance&shipping-method=collect",
        "?payment-method=stripe&shipping-method=teleport",
    ],
)
def test_checkout_invalid_methods(basket_client, basket, query):
    resp = basket_client.get(reverse("shop:checkout") + query)
    assert resp.status_code == 302
    assert resp.url == reverse("shop:basket")
    assert [str(m) for m in get_messages(resp.wsgi_request)] == [
        "Please select a shipping and payment method."
    ]
    # invalid shipping method isn't saved
    basket.refresh_from_db()
    assert basket.shipping_method == "collect"


def test_checkout_valid_methods(basket_client, basket):
    resp = basket_client.get(
        reverse("shop:checkout") + "?payment-method=stripe&shipping-method=deliver"
    )
    assert resp.status_code == 200
    basket.refresh_from_db()
    assert basket.shipping_method == "deliver"


def test_checkout_method_not_allowed(basket_client):
    url = reverse("shop:checkout") + "?payment-method=stripe&shipping-method=collect"
    assert basket_client.put(url).status_code == 405


# Basket timeout


def test_basket_timeout_other_basket(basket_client, basket):
    other_basket = baker.make("shop.Basket")
    resp = basket_client.get(reverse("shop:basket_timeout", args=(other_basket.id,)))
    # another visitor's basket's time isn't shown: the page is reloaded (showing
    # the visitor's own basket), rather than polling an error every second
    assert resp.content == b""
    assert resp.headers["HX-Refresh"] == "true"
    assert [str(m) for m in get_messages(resp.wsgi_request)] == [
        "Your basket has changed since this page was loaded."
    ]


def test_basket_timeout_no_basket(client, basket):
    # e.g. the basket has been checked out since the basket page was loaded
    resp = client.get(reverse("shop:basket_timeout", args=(basket.id,)))
    assert resp.headers["HX-Refresh"] == "true"


# Salesman API


@pytest.mark.parametrize("url", ["/api/basket/", "/api/checkout/", "/api/orders/"])
def test_salesman_api_not_exposed(client, url):
    # The salesman basket, checkout and orders API would bypass the shop views'
    # checks (stock, live products, basket locked during payment)
    assert client.get(url).status_code == 404
    assert client.post(url, {}, content_type="application/json").status_code == 404


def test_salesman_payment_urls_exposed():
    assert reverse("stripe-connect-success") == "/api/payment/stripe/success/"
    assert reverse("stripe-connect-cancel") == "/api/payment/stripe/cancel/"
    assert reverse("stripe-connect-webhook") == "/stripe/webhook/"
