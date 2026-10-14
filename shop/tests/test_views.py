from datetime import datetime, timezone
from unittest import mock

import pytest

from model_bakery import baker

from django.urls import reverse

from salesman.core.utils import get_salesman_model

from ..views import (
    add_to_basket,
    basket_view,
    decrease_quantity,
    get_basket,
    get_basket_item,
    get_basket_total,
    get_basket_quantity_and_total,
    _can_increase_quantity,
    increase_quantity,
    update_quantity,
    delete_basket_item,
    checkout_view,
    new_order_view,
    order_status_view,
)


Basket = get_salesman_model("Basket")

pytestmark = pytest.mark.django_db


def mock_as_view_resp(status_code, data):
    class MockAsViewResp:
        def __init__(self, *args, **kwargs):
            self.status_code = status_code
            self.data = data

    return MockAsViewResp


def test_get_basket(rf, freezer):
    freezer.move_to("2023-10-10 10:00")
    request = rf.get("/")
    assert not Basket.objects.exists()
    basket_resp = get_basket(request)
    assert Basket.objects.count() == 1
    assert basket_resp == {
        "extra": {},
        "extra_rows": [],
        "id": Basket.objects.first().id,
        "items": [],
        "subtotal": "0.00",
        "total": "0.00",
        "timeout": datetime(2023, 10, 10, 10, 15, tzinfo=timezone.utc),
    }


def test_get_basket_total(rf):
    request = rf.get("/")
    basket_resp = get_basket_total(request)
    assert basket_resp == "0.00"


def test_get_basket_quantity_and_total(rf):
    request = rf.get("/")
    basket_resp = get_basket_quantity_and_total(request)
    assert basket_resp == (0, "0.00")


def test_get_existing_empty_basket(rf, freezer):
    freezer.move_to("2023-10-10 10:00")
    basket = baker.make(Basket)
    request = rf.get("/")
    request.session = {"BASKET_ID": basket.id}

    assert get_basket(request) == {
        "extra": {},
        "extra_rows": [],
        "id": basket.id,
        "items": [],
        "subtotal": "0.00",
        "total": "0.00",
        "timeout": datetime(2023, 10, 10, 10, 15, tzinfo=timezone.utc),
    }


def test_get_basket_with_items(rf, basket):
    request = rf.get("/")
    request.session = {"BASKET_ID": basket.id}
    basket_resp = get_basket(request)
    basket_items = basket_resp.pop("items")
    basket_resp.pop("timeout")
    assert basket_resp == {
        "extra": {"name": "Test User"},
        "extra_rows": [],
        "id": basket.id,
        "subtotal": "20.00",
        "total": "20.00",
    }
    assert len(basket_items) == 1
    basket_item = basket_items[0]
    assert basket_item["quantity"] == 2
    assert basket_item["product"]["name"] == "Test Product - Small"


def test_get_basket_item_no_item(rf, basket):
    variant = basket.items.first().product
    request = rf.get("/")
    basket_resp = get_basket(request)
    basket_item = get_basket_item(basket_resp, variant.id)
    assert basket_item == {}


def test_get_basket_item(rf, basket):
    variant = basket.items.first().product
    request = rf.get("/")
    request.session = {"BASKET_ID": basket.id}
    basket_resp = get_basket(request)
    basket_item = get_basket_item(basket_resp, variant.id)
    assert request.session["BASKET_ID"] == basket.id
    assert basket_resp.get("id") == basket.id
    assert basket_item["product"]["name"] == "Test Product - Small"


def test_get_product_detail_view(client, product):
    resp = client.get(reverse("shop:product_detail", args=(product.id,)))
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "current_stock,increase_to,in_basket,expected",
    [
        # changing quantity to 1
        # out of stock
        (0, 1, False, False),
        # But if we're in the basket, it's actually a decrease (basket quantity is 2)
        (0, 1, True, True),
        # stock 1; can increase to 1 from in and out of basket
        (1, 1, False, True),
        (1, 1, True, True),
        # can increase basket quantity to 3 (currently 2) from in basket but not outside
        (1, 3, True, True),
        (1, 3, False, False),
    ],
)
def test_can_increase_quantity(
    rf, basket, product, current_stock, increase_to, in_basket, expected
):
    # 2 items in basket already
    variant = product.variants.first()
    variant.stock = current_stock
    variant.save()

    request = rf.get("/")
    request.session = {"BASKET_ID": basket.id}

    assert _can_increase_quantity(request, variant, increase_to, in_basket) == expected


def test_increase_quantity_can_increase(rf, basket, product):
    # 2 items in basket already, ensure we can increase
    variant = product.variants.first()
    variant.stock = 2
    variant.save()
    # salesman requires that the parameter name when submitting a product to the
    # basket is "product_id"; a basket product is actually a product variant
    url = (
        reverse("shop:increase_quantity", args=(product.id,))
        + f"?product_id={variant.id}&quantity=1"
    )
    request = rf.get(url)
    request.session = {"BASKET_ID": basket.id}

    response = increase_quantity(request, product.id)
    assert response.headers["HX-Trigger"] == "quantity-changed"
    assert "value=2" in response.content.decode()


def test_increase_quantity_cannot_increase(rf, basket, product):
    # 2 items in basket already, can't increase
    variant = product.variants.first()
    variant.stock = 0
    variant.save()
    # salesman requires that the parameter name when submitting a product to the
    # basket is "product_id"; a basket product is actually a product variant
    url = (
        reverse("shop:increase_quantity", args=(product.id,))
        + f"?product_id={variant.id}&quantity=2"
    )
    request = rf.get(url)
    request.session = {"BASKET_ID": basket.id}

    response = increase_quantity(request, product.id)
    assert "HX-Trigger" not in response.headers
    assert "value=2" in response.content.decode()


def test_increase_quantity_from_basket(rf, basket, product):
    # 2 items in basket already, ensure we can increase
    variant = product.variants.first()
    variant.stock = 0
    variant.save()
    # salesman requires that the parameter name when submitting a product to the
    # basket is "product_id"; a basket product is actually a product variant
    url = (
        reverse("shop:increase_quantity", args=(product.id,))
        + f"?product_id={variant.id}&quantity=1&ref=basket"
    )
    request = rf.get(url)
    request.session = {"BASKET_ID": basket.id}

    response = increase_quantity(request, product.id)
    assert response.headers["HX-Trigger"] == "quantity-changed"
    assert "value=2" in response.content.decode()


@pytest.mark.parametrize("current_quantity,expected", [(1, 1), (2, 1), (3, 2)])
def test_decrease_quantity(rf, basket, product, current_quantity, expected):
    variant = product.variants.first()
    variant.stock = 0
    variant.save()
    # salesman requires that the parameter name when submitting a product to the
    # basket is "product_id"; a basket product is actually a product variant
    url = (
        reverse("shop:decrease_quantity", args=(product.id,))
        + f"?product_id={variant.id}&quantity={current_quantity}"
    )
    request = rf.get(url)
    request.session = {"BASKET_ID": basket.id}

    response = decrease_quantity(request, product.id)
    assert response.headers["HX-Trigger"] == "quantity-changed"
    assert f"value={expected}" in response.content.decode()


def test_basket_view(rf, basket, product):
    request = rf.get(reverse("shop:basket"))
    request.session = {"BASKET_ID": basket.id}
    resp = basket_view(request)
    assert resp.context_data["payment_methods"] == [
        {
            "identifier": "stripe",
            "label": "Pay with Stripe",
            "error": None,
            "help": "Pay with stripe",
        }
    ]
    assert resp.context_data["shipping_methods"] == [
        ("collect", "Collect in store"),
        ("deliver", "Delivery"),
    ]
    # basket items are converted to a dict keyed by product, with product type and category added
    assert list(resp.context_data["basket"]["items"].keys()) == [product.identifier]
    item = resp.context_data["basket"]["items"][product.identifier][0]
    assert item["product_type"] == product.name
    assert item["category"] == product.category_page.title


def test_add_to_basket(rf, product):
    # setup empty basket
    request = rf.get("/")
    basket_id = get_basket(request)["id"]
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10, stock=4
    )
    request = rf.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "quantity": 3,
            "product_id": variant.id,
            "product_type": "shop.ProductVariant",
        },
    )
    request.session = {"BASKET_ID": basket_id}
    resp = add_to_basket(request, product.id)
    content = resp.content.decode()
    # 3 items in basket
    assert '<i class="fa-solid fa-basket-shopping"></i>  (3)' in content
    # quantity reset to 1
    assert (
        f'id="id_quantity_{product.id}" name="quantity" type="number" value=1'
        in content
    )
    assert f'<option value="{variant.id}">Small - £10.00 (1 in stock)</option>'


def test_add_to_basket_out_of_stock(rf, basket, product):
    # setup empty basket
    variant1 = product.variants.first()
    variant1.stock = 2
    variant1.save()
    variant2 = baker.make(
        "shop.ProductVariant", product=product, variant_name="Medium", price=10, stock=2
    )
    # add to basket so variant1 becomes out of stock
    request = rf.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "quantity": 2,
            "product_id": variant1.id,
            "product_type": "shop.ProductVariant",
        },
    )
    request.session = {"BASKET_ID": basket.id}
    resp = add_to_basket(request, product.id)
    content = resp.content.decode()
    # 4 item now in basket
    assert '<i class="fa-solid fa-basket-shopping"></i>  (4)' in content

    # variant 1 out of stock; another variant still in stock, so quantity and +/- buttons still shown
    assert (
        f'id="id_quantity_{product.id}" name="quantity" type="number" value=1'
        in content
    )
    assert (
        f'<option disabled=disabled value="{variant1.id}">Small - £10.00 (out of stock)</option>'
        in content
    )
    assert f'<option value="{variant2.id}">Medium - £10.00 (2 in stock)</option>'

    # add to basket so variant2 now also out of stock
    request = rf.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "quantity": 2,
            "product_id": variant2.id,
            "product_type": "shop.ProductVariant",
        },
    )
    request.session = {"BASKET_ID": basket.id}
    resp = add_to_basket(request, product.id)
    content = resp.content.decode()
    # 6 items now in basket
    assert '<i class="fa-solid fa-basket-shopping"></i>  (6)' in content

    # so quantity and +/- buttons hidden
    assert (
        f'id="id_quantity_{product.id}" name="quantity" type="number" value=1'
        not in content
    )
    assert '<div class="text-danger">Out of stock</div>' in content


def test_add_to_basket_with_error(rf, product):
    # setup empty basket
    request = rf.get("/")
    basket_id = get_basket(request)["id"]
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10, stock=4
    )
    request = rf.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "quantity": 3,
            "product_id": variant.id,
            "product_type": "shop.ProductVariant",
        },
    )
    request.session = {"BASKET_ID": basket_id}

    with mock.patch("shop.views.BasketViewSet.as_view") as mock_basket_as_view:
        mock_basket_as_view.return_value = mock_as_view_resp(
            status_code=400, data={"quantity": 0}
        )
        resp = add_to_basket(request, product.id)
    content = resp.content.decode()
    assert "Something went wrong" in content


def test_add_to_basket_cant_increase(rf, product):
    # setup empty basket
    request = rf.get("/")
    basket_id = get_basket(request)["id"]
    # variant with 1 in stock
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10, stock=1
    )
    # try to add 2 to basked
    request = rf.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "quantity": 2,
            "product_id": variant.id,
            "product_type": "shop.ProductVariant",
        },
    )
    request.session = {"BASKET_ID": basket_id}
    resp = add_to_basket(request, product.id)
    content = resp.content.decode()
    # no items in basket
    assert '<i class="fa-solid fa-basket-shopping"></i>  (0)' in content
    assert "Quantity requested is not available" in content


### Update quantity from basket


def test_update_quantity(rf, basket):
    # basket has 1 variant, quantity 2
    assert basket.items.count() == 1
    basket_item = basket.items.first()
    assert basket_item.quantity == 2
    variant_id = basket_item.product.id

    # product ID in post is the product variant
    data = {"quantity": 3, "product_id": variant_id}
    request = rf.post(
        reverse("shop:update_quantity", args=(basket_item.ref,)), data=data
    )
    request.session = {"BASKET_ID": basket.id}

    update_quantity(request, basket_item.ref)

    # refresh_from_db isn't enough to get the update basket here
    basket = Basket.objects.get(id=basket.id)
    assert basket.quantity == 3


def test_update_quantity_nothing_to_update(rf, basket):
    # basket has 1 variant, quantity 2
    basket_item = basket.items.first()
    variant_id = basket_item.product.id
    # product ID in post is the product variant
    # update to same quantity
    data = {"quantity": 2, "product_id": variant_id}
    request = rf.post(
        reverse("shop:update_quantity", args=(basket_item.ref,)), data=data
    )
    request.session = {"BASKET_ID": basket.id}

    update_quantity(request, basket_item.ref)

    # refresh_from_db isn't enough to get the update basket here
    basket = Basket.objects.get(id=basket.id)
    assert basket.quantity == 2


def test_update_quantity_with_error(rf, basket):
    # basket has 1 variant, quantity 2
    basket_item = basket.items.first()
    variant_id = basket_item.product.id
    # product ID in post is the product variant
    # update to same quantity
    data = {"quantity": 2, "product_id": variant_id}
    request = rf.post(
        reverse("shop:update_quantity", args=(basket_item.ref,)), data=data
    )
    request.session = {"BASKET_ID": basket.id}

    with mock.patch("shop.views.BasketViewSet.as_view") as mock_basket_as_view:
        mock_basket_as_view.return_value = mock_as_view_resp(
            status_code=400, data={"quantity": 4}
        )
        resp = update_quantity(request, basket_item.ref)

    # refresh_from_db isn't enough to get the update basket here
    basket = Basket.objects.get(id=basket.id)
    assert basket.quantity == 2
    assert "Error" in resp.content.decode()


### Delete items from basket


def test_sole_delete_basket_item(rf, basket):
    # basket has 1 variant, quantity 2
    assert basket.items.count() == 1
    basket_item = basket.items.first()
    variant_id = basket_item.product.id
    # product ID in post is the product variant
    data = {"product_id": variant_id}
    request = rf.post(
        reverse("shop:delete_basket_item", args=(basket_item.ref,)), data=data
    )
    request.session = {"BASKET_ID": basket.id}

    resp = delete_basket_item(request, basket_item.ref)
    assert "Basket is empty." in resp.content.decode()
    # refresh_from_db isn't enough to get the update basket here
    basket = Basket.objects.get(id=basket.id)
    assert basket.quantity == 0


def test_delete_basket_item_other_variants_left(rf, basket):
    basket_item = basket.items.first()
    variant = basket_item.product
    product = variant.product

    # Make another variant for this product and add to basket
    variant1 = baker.make(
        "shop.ProductVariant",
        product=product,
        variant_name="Medium",
        price=15,
        stock=5,
    )
    basket.add(variant1, quantity=1)
    basket.update(request=None)
    assert basket.quantity == 3
    assert basket.total == 35

    # product ID in post is the product variant
    data = {"product_id": variant.id}
    request = rf.post(
        reverse("shop:delete_basket_item", args=(basket_item.ref,)), data=data
    )
    request.session = {"BASKET_ID": basket.id}
    # delete the original variant
    resp = delete_basket_item(request, basket_item.ref)
    # this hides just the variant row
    assert (
        f"<div id='row-{variant.id}' hx-swap-oob='true'></div>" in resp.content.decode()
    )
    # this updates the total
    assert f"<span id='total' hx-swap-oob='true'>15.00</span>" in resp.content.decode()

    # refresh_from_db isn't enough to get the update basket here
    basket = Basket.objects.get(id=basket.id)
    basket.update(request)
    assert basket.quantity == 1
    assert basket.total == 15


def test_delete_basket_item_other_products_left(rf, basket, category_page):
    basket_item = basket.items.first()
    variant = basket_item.product
    product = variant.product

    # Make another variant for another product and add to basket
    new_product = baker.make("shop.Product", name="Mug", category_page=category_page)
    variant1 = baker.make("shop.ProductVariant", product=new_product, price=5, stock=5)
    basket.add(variant1, quantity=1)
    basket.update(request=None)
    assert basket.quantity == 3
    assert basket.total == 25

    # product ID in post is the product variant
    data = {"product_id": variant.id}
    request = rf.post(
        reverse("shop:delete_basket_item", args=(basket_item.ref,)), data=data
    )
    request.session = {"BASKET_ID": basket.id}
    # delete the original variant
    resp = delete_basket_item(request, basket_item.ref)

    # this hides the entire row for the deleted product
    assert (
        f"<div id='row-{product.identifier}' hx-swap-oob='true'></div>"
        in resp.content.decode()
    )
    # this updates the total
    assert f"<span id='total' hx-swap-oob='true'>5.00</span>" in resp.content.decode()

    # refresh_from_db isn't enough to get the update basket here
    basket = Basket.objects.get(id=basket.id)
    basket.update(request)
    assert basket.quantity == 1
    assert basket.total == 5


def test_delete_basket_item_with_error(rf, basket):
    basket_item = basket.items.first()
    variant_id = basket_item.product.id
    data = {"product_id": variant_id}
    request = rf.post(
        reverse("shop:update_quantity", args=(basket_item.ref,)), data=data
    )
    request.session = {"BASKET_ID": basket.id}

    with mock.patch("shop.views.BasketViewSet.as_view") as mock_basket_as_view:
        mock_basket_as_view.return_value = mock_as_view_resp(
            status_code=400, data={"quantity": 2}
        )
        resp = delete_basket_item(request, basket_item.ref)

    # refresh_from_db isn't enough to get the update basket here
    basket = Basket.objects.get(id=basket.id)
    # no change to basket
    assert basket.quantity == 2
    assert "Error" in resp.content.decode()


## CHECKOUT VIEW


def test_get_checkout_view(rf, basket):
    request = rf.get(
        reverse("shop:checkout") + "?payment-method=stripe&shipping-method=deliver"
    )
    request.session = {"BASKET_ID": basket.id}

    resp = checkout_view(request)
    assert resp.status_code == 200
    basket = Basket.objects.get(id=basket.id)
    assert basket.shipping_method == "deliver"


@mock.patch("shop.views.CheckoutViewSet.as_view")
def test_post_checkout_view(mock_checkout, rf, basket):
    mock_checkout.return_value = mock_as_view_resp(
        status_code=201, data={"url": "https://test-checkout"}
    )

    form_data = {
        "email": "test@test.com",
        "email1": "test@test.com",
        "name": "Test",
        "payment_method": "stripe",
        "shipping_method": "collect",
        "billing_address": "-",
        "shipping_address": "-",
    }
    request = rf.post(
        reverse("shop:checkout") + "?payment-method=stripe&shipping-method=collect",
        data=form_data,
    )
    request.session = {"BASKET_ID": basket.id}
    resp = checkout_view(request)

    # redirects to the stripe payment method from the mock checkout call
    assert resp.status_code == 302
    assert resp.url == "https://test-checkout"


def test_post_checkout_view_invalid_form(rf, basket):
    form_data = {
        "email": "test@test.com",
        "email1": "tst@test.com",
        "name": "Test",
        "payment_method": "stripe",
        "shipping_method": "collect",
        "billing_address": "-",
        "shipping_address": "-",
    }
    request = rf.post(
        reverse("shop:checkout") + "?payment-method=stripe&shipping-method=collect",
        data=form_data,
    )
    request.session = {"BASKET_ID": basket.id}
    resp = checkout_view(request)

    # redirects to the stripe payment method from the mock checkout call
    assert resp.status_code == 200
    assert resp.context_data["form"].errors == {"email1": ["Email fields do not match"]}


@mock.patch("shop.views.CheckoutViewSet.as_view")
def test_post_checkout_view_non_stripe_payment_method(mock_checkout, rf, basket):
    mock_checkout.return_value = mock_as_view_resp(
        status_code=201, data={"url": "https://test-checkout?token=foo"}
    )

    form_data = {
        "email": "test@test.com",
        "email1": "test@test.com",
        "name": "Test",
        "payment_method": "stripe",
        "shipping_method": "collect",
        "billing_address": "-",
        "shipping_address": "-",
    }
    request = rf.post(
        reverse("shop:checkout")
        + "?payment-method=pay-in-advance&shipping-method=collect",
        data=form_data,
    )
    request.session = {"BASKET_ID": basket.id}
    resp = checkout_view(request)

    # redirects to the new order status using the token from the mock checkout call
    assert resp.status_code == 302
    assert resp.url == reverse("shop:new_order_status", args=("foo",))


@mock.patch("shop.views.CheckoutViewSet.as_view")
def test_post_checkout_view_error(mock_checkout, rf, basket):
    mock_checkout.return_value = mock_as_view_resp(
        status_code=400, data={"url": "https://test-checkout?token=foo"}
    )

    form_data = {
        "email": "test@test.com",
        "email1": "test@test.com",
        "name": "Test",
        "payment_method": "stripe",
        "shipping_method": "collect",
        "billing_address": "-",
        "shipping_address": "-",
    }
    request = rf.post(
        reverse("shop:checkout") + "?payment-method=stripe&shipping-method=collect",
        data=form_data,
    )
    request.session = {"BASKET_ID": basket.id}
    resp = checkout_view(request)

    # redirects to the new order status using the token from the mock checkout call
    assert resp.status_code == 200
    assert "checkout_error" in resp.context_data


### ORDER STATUS VIEWS


def test_order_status_view(rf, order):
    request = rf.get("/")
    resp = order_status_view(request, order.token)
    order_context = resp.context_data["order"]
    # order has relevant order info, plus rejigged basket info
    # These are not on the serialised object
    assert "amount_outstanding" in order_context
    assert "amount_paid" in order_context
    # items are organised by product identifier
    assert len(order_context["items"]["test-category-test-product"]) == 1
    # and has category added in
    assert (
        order_context["items"]["test-category-test-product"][0]["category"]
        == "Test Category"
    )
    assert resp.context_data["hide_basket"]
    assert not resp.context_data["new_order"]
    assert "Amount paid: £0" in resp.rendered_content
    assert "Thank you for your order!" not in resp.rendered_content


def test_new_order_status_view(rf, order):
    request = rf.get("/")
    resp = new_order_view(request, order.token)
    assert resp.context_data["hide_basket"]
    assert resp.context_data["new_order"]
    assert "Thank you for your order!" in resp.rendered_content


def test_basket_timeout_view(client, basket, freezer):
    url = reverse("shop:basket_timeout", args=(basket.id,))
    headers = {"hx-request": True}
    # Set current time
    freezer.move_to(datetime(2023, 10, 1, 12, 0, tzinfo=timezone.utc))

    # basket times out in 10 mins
    basket.timeout = datetime(2023, 10, 1, 12, 10, tzinfo=timezone.utc)
    basket.save()
    resp = client.get(url, headers=headers)
    assert resp.content.decode() == "10m 0s"

    # basket times out in 5.5 mins
    freezer.move_to(datetime(2023, 10, 1, 12, 4, 30, tzinfo=timezone.utc))
    resp = client.get(url, headers=headers)
    assert resp.content.decode() == "5m 30s"

    # basket times out now
    freezer.move_to(datetime(2023, 10, 1, 12, 10, tzinfo=timezone.utc))
    resp = client.get(url, headers=headers)
    assert resp.content.decode() == "0m 0s"

    # basket has expired
    freezer.move_to(datetime(2023, 10, 1, 12, 10, 30, tzinfo=timezone.utc))
    resp = client.get(url, headers=headers)
    assert resp.status_code == 302
    assert resp.url == reverse("shop:basket")
    assert not basket.items.exists()

    # basket has no items
    resp = client.get(url, headers=headers)
    assert (
        resp.content.decode()
        == "<div></div><div id='basket-countdown-container' hx-swap-oob='true'></div>"
    )
