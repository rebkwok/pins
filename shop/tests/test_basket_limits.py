"""
Baskets' limits (SHOP_MAX_ITEM_QUANTITY of each item, SHOP_MAX_BASKET_ITEMS in
all), so one basket (e.g. a bot's) can't hold a lot of the shop's stock; and
the log when they're reached
"""

import logging

import pytest
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from ..views import client_ip

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")


@pytest.fixture(autouse=True)
def limits(settings):
    settings.SHOP_MAX_ITEM_QUANTITY = 3
    settings.SHOP_MAX_BASKET_ITEMS = 5


@pytest.fixture
def mug(product):
    return baker.make("shop.ProductVariant", product=product, variant_name="Mug", stock=20)


@pytest.fixture
def cup(product):
    return baker.make("shop.ProductVariant", product=product, variant_name="Cup", stock=20)


@pytest.fixture
def raffle(category):
    product = baker.make("shop.Product", category=category, name="Raffle", price=1, unlimited_stock=True)
    return baker.make("shop.ProductVariant", product=product)


def add(client, variant, quantity):
    return client.post(
        reverse("shop:add_to_basket", args=(variant.product_id,)),
        {"variant_id": variant.id, "quantity": quantity},
        HTTP_X_REAL_IP="203.0.113.7",
    ).content.decode()


def basket_quantity(variant):
    item = Basket.objects.get().items.filter(product_id=variant.id).first()
    return item.quantity if item else 0


CONTACT = "Please <a href=\"/contact-us/\">contact us</a> if you'd like to order more."


def test_add_over_item_limit(client, mug, caplog):
    assert "Added!" in add(client, mug, 3)
    content = add(client, mug, 1)
    # (saying how to order more)
    assert f"Sorry, you can only have 3 of each item in your basket. {CONTACT}" in content
    assert "View basket" in content
    assert basket_quantity(mug) == 3
    mug.refresh_from_db()
    assert mug.stock == 17
    # logged, with the visitor's address (nginx's X-Real-IP)
    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    message = record.getMessage()
    assert message == (
        f"Basket limit reached: 4 x {mug} for basket {Basket.objects.get().id} (3 items), from "
        "203.0.113.7: Sorry, you can only have 3 of each item in your basket."
    )


def test_add_over_basket_limit(client, mug, cup):
    add(client, mug, 3)
    content = add(client, cup, 3)
    assert f"Sorry, your basket can only hold 5 items. {CONTACT}" in content
    assert basket_quantity(cup) == 0
    assert "Added!" in add(client, cup, 2)


def test_no_limit_for_unlimited_stock(client, mug, raffle):
    # (they hold no stock): not limited, or counted
    assert "Added!" in add(client, raffle, 20)
    assert "Added!" in add(client, mug, 3)
    assert basket_quantity(raffle) == 20


def update(client, variant, quantity):
    basket = Basket.objects.get()
    item = basket.items.get(product_id=variant.id)
    return client.post(
        reverse("shop:update_quantity", args=(item.ref,)),
        {"variant_id": variant.id, "quantity": quantity},
    ).content.decode()


def test_update_over_limits(client, mug, cup, caplog):
    add(client, mug, 1)
    add(client, cup, 3)
    content = update(client, mug, 4)
    assert f"Sorry, you can only have 3 of each item in your basket. {CONTACT}" in content
    # (the field back to the item's quantity, its max the limits)
    assert 'value="1" max="2"' in content
    assert basket_quantity(mug) == 1
    content = update(client, mug, 3)
    assert "Sorry, your basket can only hold 5 items." in content
    assert basket_quantity(mug) == 1
    assert "Basket updated" in update(client, mug, 2)
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    # decreasing is always allowed
    assert "Basket updated" in update(client, cup, 1)


def increase(client, variant, quantity, in_basket=False):
    params = {"variant_id": variant.id, "quantity": quantity}
    if in_basket:
        params["ref"] = "basket"
    form_id = variant.id if in_basket else variant.product_id
    return client.get(reverse("shop:increase_quantity", args=(form_id,)), params).content.decode()


def test_increase_button_stops_at_limits(client, mug, cup):
    # the + button: on the shop's pages, up to the limit less what's in the
    # basket; in the basket, up to the limit
    add(client, mug, 1)
    content = increase(client, mug, 2)
    assert 'value="2" max="2"' in content
    assert f"Sorry, you can only have 3 of each item in your basket. {CONTACT}" in content
    assert 'value="2"' in increase(client, mug, 1)
    content = increase(client, mug, 3, in_basket=True)
    assert 'value="3" max="3"' in content
    assert "Sorry, you can only have 3 of each item in your basket." in content
    # the basket's limit
    add(client, cup, 3)
    content = increase(client, mug, 1, in_basket=True)
    assert 'value="2" max="2"' in content
    assert "Sorry, your basket can only hold 5 items." not in content
    content = increase(client, mug, 2, in_basket=True)
    assert "Sorry, your basket can only hold 5 items." in content


def test_increase_unlimited_stock(client, raffle):
    content = increase(client, raffle, 50)
    assert 'value="51"' in content
    assert "max=" not in content


def test_client_ip(rf):
    assert client_ip(rf.get("/", HTTP_X_REAL_IP="203.0.113.7", REMOTE_ADDR="10.0.0.1")) == "203.0.113.7"
    assert client_ip(rf.get("/", REMOTE_ADDR="10.0.0.1")) == "10.0.0.1"
