"""
Pack variants that share stock with single items: e.g. single cards and packs
of 5, sold from the product's stock of cards.
"""
import html
import json
import re

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.db import IntegrityError, transaction
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from ..models import PACK_SIZE_NOT_SHARED_MESSAGE, SHARED_STOCK_COLOUR_SIZE_MESSAGE, ProductVariant
from ..views import add_to_basket, increase_quantity
from .factories import PRODUCT_FORM_DEFAULTS

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")


@pytest.fixture
def cards(product):
    """A product with 13 cards in stock, sold singly or in packs of 5"""
    product.shares_stock = True
    product.stock = 13
    product.save()
    return product


@pytest.fixture
def single(cards):
    return baker.make(
        ProductVariant, product=cards, variant_name="Single", price=2, stock=0, pack_size=1
    )


@pytest.fixture
def pack(cards):
    return baker.make(
        ProductVariant, product=cards, variant_name="Pack of 5", price=8, stock=0, pack_size=5
    )


def stock(product):
    product.refresh_from_db()
    return product.stock


# The model


def test_shared_stock(cards, single, pack):
    assert (single.stock_holder, single.items_per_unit, single.available) == (cards, 1, 13)
    assert (pack.stock_holder, pack.items_per_unit, pack.available) == (cards, 5, 2)
    assert pack.has_stock_for(2)
    assert not pack.has_stock_for(3)
    # with 1 pack already taken from stock by the basket (so 8 left), 2 packs
    # in all is fine, but 3 isn't
    cards.stock = 8
    assert pack.has_stock_for(2, in_basket=1)
    assert not pack.has_stock_for(3, in_basket=1)


def test_separate_stock(product):
    # without shared stock, a variant's own stock is used, and its pack size
    # isn't (e.g. a "Pack of 5" variant whose stock counts packs)
    variant = baker.make(ProductVariant, product=product, stock=3, pack_size=5)
    assert (variant.stock_holder, variant.items_per_unit, variant.available) == (variant, 1, 3)
    assert variant.has_stock_for(3)
    assert not variant.has_stock_for(4)


def test_stock_display(cards, single, pack, product):
    assert single.stock_display() == "13 (shared stock)"
    assert pack.stock_display() == "2 packs (from 13 shared)"
    cards.shares_stock = False
    single.stock = 4
    assert single.stock_display() == 4


def test_out_of_stock(cards, single, pack):
    assert not cards.out_of_stock()
    # not enough for a pack, but enough for a single
    cards.stock = 4
    assert not cards.out_of_stock()
    single.live = False
    single.save()
    assert cards.out_of_stock()
    cards.stock = 5
    assert not cards.out_of_stock()
    cards.stock = 0
    single.live = True
    single.save()
    assert cards.out_of_stock()


# Stock changes from baskets and orders


def test_basket_takes_shared_stock(cards, single, pack):
    basket = baker.make(Basket)
    basket.add(pack, quantity=2)
    assert stock(cards) == 3
    basket.add(single, quantity=3)
    assert stock(cards) == 0
    # updating the quantity
    item = basket.find(basket.items.get(product_id=pack.id).ref)
    item.quantity = 1
    item.save()
    assert stock(cards) == 5
    # removing an item
    basket.remove(item.ref)
    assert stock(cards) == 10
    # clearing the basket returns the rest
    basket.clear()
    assert stock(cards) == 13
    # the variants' own stock isn't changed
    single.refresh_from_db()
    pack.refresh_from_db()
    assert (single.stock, pack.stock) == (0, 0)


def test_order_keeps_shared_stock(cards, single, pack):
    # deleting the basket after an order is created from it doesn't return the
    # ordered items to stock
    basket = baker.make(Basket)
    basket.add(pack, quantity=2)
    basket.add(single, quantity=1)
    Order.objects.create_from_basket(basket, None)
    basket.delete()
    assert stock(cards) == 2


# The shop


def basket_session(request, basket=None):
    request.session = {"BASKET_ID": basket.id} if basket else {}
    request.user = AnonymousUser()
    return request


def test_dropdown(client, cards, single, pack):
    content = " ".join(
        client.get(reverse("shop:product_detail", args=(cards.id,))).content.decode().split()
    )
    # the prices differ, so are shown; stock only if it's low (2 packs of 5 left)
    assert "From <strong>£2.00</strong>" in content
    assert "> Single – £2.00 </option>" in content
    assert "> Pack of 5 – £8.00 (only 2 left) </option>" in content


def test_dropdown_pack_out_of_stock(client, cards, single, pack):
    cards.stock = 4
    cards.save()
    content = " ".join(
        client.get(reverse("shop:product_detail", args=(cards.id,))).content.decode().split()
    )
    assert "Single – £2.00 (only 4 left)" in content
    assert "disabled> Pack of 5 – £8.00 (out of stock) </option>" in content


def post_add(rf, cards, variant, quantity, basket=None):
    request = rf.post(
        reverse("shop:add_to_basket", args=(cards.id,)),
        {"variant_id": variant.id, "quantity": quantity},
    )
    return add_to_basket(basket_session(request, basket), cards.id).content.decode()


def test_add_packs(rf, cards, single, pack):
    content = post_add(rf, cards, pack, 2)
    assert "Added!" in content
    assert stock(cards) == 3
    # the dropdown is updated: no packs left, 3 singles
    assert "(only 3 left)" in content
    assert "(out of stock)" in content


def test_add_too_many_packs(rf, cards, single, pack):
    content = post_add(rf, cards, pack, 3)
    # 13 singles: 2 packs of 5
    assert "Only 2 available</div>" in content
    # the quantity is lowered to what's available, with that as its max
    assert 'value="2" max="2"' in content
    assert stock(cards) == 13


def test_add_last_items_out_of_stock(rf, cards, single, pack):
    content = post_add(rf, cards, single, 13)
    assert "Added!" in content
    assert stock(cards) == 0
    # the product is out of stock: no quantity or add button
    assert f"<div id='change_quantity_wrapper_{cards.id}' hx-swap-oob='true'></div>" in content


def test_increase_quantity_button(rf, cards, single, pack):
    def increase(value, basket=None, ref=""):
        url = reverse("shop:increase_quantity", args=(cards.id,))
        request = rf.get(url, {"variant_id": pack.id, "quantity": value, "ref": ref})
        return increase_quantity(basket_session(request, basket), cards.id).content.decode()

    # from 1 to 2 packs is fine; 3 isn't (shown by the product's form)
    assert "available</div>" not in increase(1)
    assert f"<div id='added_{cards.id}' class='alert-danger' hx-swap-oob='true'>Only 2 available</div>" in increase(2)
    # in the basket, with 2 packs already taken from stock (3 left): shown
    # under the item, and the field's max is the 2 in the basket
    basket = baker.make(Basket)
    basket.add(pack, quantity=2)
    content = increase(2, basket, ref="basket")
    assert f"<div id='updated_{cards.id}' class='alert-danger' hx-swap-oob='true'>Only 2 available</div>" in content
    assert 'value="2" max="2"' in content
    assert "available</div>" not in increase(1, basket, ref="basket")


def test_update_quantity_in_basket(client, cards, single, pack):
    basket = baker.make(Basket)
    basket.add(pack, quantity=1)
    session = client.session
    session["BASKET_ID"] = basket.id
    session.save()
    item = basket.items.get()
    url = reverse("shop:update_quantity", args=(item.ref,))
    # 8 left: 2 more packs is fine (3 in all), 3 more isn't
    content = client.post(url, {"variant_id": pack.id, "quantity": 4}).content.decode()
    assert "Quantity requested is not available" in content
    assert stock(cards) == 8
    content = client.post(url, {"variant_id": pack.id, "quantity": 2}).content.decode()
    assert "Basket updated" in content
    assert stock(cards) == 3


# The admin


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    return client


def product_form_data(product, variants, **data):
    form = {
        "category": product.category.id,
        "name": product.name,
        "price": str(product.price),
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "live": "on",
        **PRODUCT_FORM_DEFAULTS,
        "shares_stock": "on" if product.shares_stock else "",
        "stock": str(product.stock),
        "stock_shown": str(product.stock),
        "variants-TOTAL_FORMS": str(len(variants)),
        "variants-INITIAL_FORMS": str(len(variants)),
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
    }
    for i, variant in enumerate(variants):
        form.update(
            {
                f"variants-{i}-id": str(variant.id),
                f"variants-{i}-variant_name": variant.variant_name,
                f"variants-{i}-price": str(variant.price),
                f"variants-{i}-stock": str(variant.stock),
                f"variants-{i}-stock_shown": str(variant.stock),
                f"variants-{i}-pack_size": str(variant.pack_size),
                f"variants-{i}-live": "on",
                f"variants-{i}-ORDER": str(i + 1),
            }
        )
    form.update(data)
    return {key: value for key, value in form.items() if value != ""}


def edit_url(product):
    return reverse("wagtailsnippets_shop_product:edit", args=(product.id,))


def test_admin_shared_stock_change(admin_client, cards, single, pack):
    # the form showed 13; meanwhile 5 were added to a basket (8 left); saving
    # with 20 adds 7, giving 15
    data = product_form_data(cards, [single, pack], stock="20")
    basket = baker.make(Basket)
    basket.add(pack, quantity=1)
    resp = admin_client.post(edit_url(cards), data)
    assert resp.status_code == 302
    assert stock(cards) == 15


def test_admin_shared_stock_negative(admin_client, cards, single, pack):
    data = product_form_data(cards, [single, pack], stock="-1")
    resp = admin_client.post(edit_url(cards), data)
    assert resp.status_code == 200
    assert "Stock can&#x27;t be negative." in resp.content.decode()
    assert stock(cards) == 13


def test_admin_start_sharing_stock(admin_client, product):
    # ticking "Variants share stock" (stock starts at 0, then set)
    variant = baker.make(ProductVariant, product=product, stock=4, price=5)
    product.shares_stock = True
    data = product_form_data(product, [variant], stock="10", stock_shown="0")
    resp = admin_client.post(edit_url(product), data)
    assert resp.status_code == 302
    product.refresh_from_db()
    assert (product.shares_stock, product.stock) == (True, 10)


def variant_fields(content):
    """The variants' stock and pack size inputs' types (None if not shown)"""
    fields = {}
    for name in ["stock", "pack_size"]:
        match = re.search(rf'type="(\w+)" name="variants-0-{name}"', content)
        fields[name] = match.group(1) if match else None
    return fields


def test_admin_shared_stock_hides_variant_stock(admin_client, cards, single):
    content = admin_client.get(edit_url(cards)).content.decode()
    assert variant_fields(content) == {"stock": None, "pack_size": "number"}
    assert "Variants share stock" in content
    assert "Shared stock" in content


def test_admin_separate_stock_shows_pack_size(admin_client, product):
    # so it can be set in the same save as ticking "Variants share stock"
    baker.make(ProductVariant, product=product, stock=4)
    content = admin_client.get(edit_url(product)).content.decode()
    assert variant_fields(content) == {"stock": "number", "pack_size": "number"}


def test_admin_start_sharing_stock_with_packs(admin_client, product):
    # ticking "Variants share stock" and setting pack sizes in one save
    single = baker.make(ProductVariant, product=product, variant_name="Single", stock=25, price=12)
    pack = baker.make(ProductVariant, product=product, variant_name="Pack of 3", stock=5, price=30)
    product.shares_stock = True
    data = product_form_data(product, [single, pack], stock="25", stock_shown="0")
    data["variants-1-pack_size"] = "3"
    resp = admin_client.post(edit_url(product), data)
    assert resp.status_code == 302
    pack.refresh_from_db()
    assert (pack.pack_size, pack.available) == (3, 8)


def variant_edit_url(variant):
    return reverse("wagtailsnippets_shop_productvariant:edit", args=(variant.id,))


def test_variant_page_shared_stock(admin_client, cards, pack):
    content = admin_client.get(variant_edit_url(pack)).content.decode()
    assert "This product's variants share stock: <strong>13</strong> single items" in content
    assert f'<a href="{edit_url(cards)}">product\'s page</a>' in content
    # the variant's own stock isn't used, so isn't shown
    assert 'name="stock"' not in content
    assert "Quantity of this item currently in stock" not in content


def test_variant_page_separate_stock(admin_client, product):
    variant = baker.make(ProductVariant, product=product, variant_name="Single", stock=4)
    baker.make(ProductVariant, product=product, variant_name="Pack of 5", stock=1)
    content = admin_client.get(variant_edit_url(variant)).content.decode()
    assert "tick 'Variants share stock' on the" in content
    assert f'<a href="{edit_url(product)}">product\'s page</a>' in content


@pytest.mark.parametrize(
    "variants",
    [
        # only one variant: nothing to share
        [{"variant_name": "Mug"}],
        # different colours or sizes are different items
        [{"colour": "Black"}, {"colour": "White"}],
        [{"variant_name": "Single", "size": "S"}, {"variant_name": "Pack"}],
    ],
)
def test_variant_page_no_shared_stock_hint(admin_client, product, variants):
    made = [baker.make(ProductVariant, product=product, **fields) for fields in variants]
    content = admin_client.get(variant_edit_url(made[0])).content.decode()
    assert "Variants share stock" not in content


def test_new_variant_page(admin_client):
    content = html.unescape(
        admin_client.get(reverse("wagtailsnippets_shop_productvariant:add")).content.decode()
    )
    assert "this is set on the product's page." in content


def test_shared_stock_variants_no_colour_or_size(admin_client, cards, single, pack):
    # sharing stock is for the same item, sold singly or in packs
    data = product_form_data(cards, [single, pack], stock="13", stock_shown="13")
    data["variants-0-colour"] = "Red"
    data["variants-1-size"] = "A5"
    resp = admin_client.post(edit_url(cards), data)
    assert resp.status_code == 200
    forms = resp.context["form"].formsets["variants"].forms
    assert forms[0].errors["colour"] == [SHARED_STOCK_COLOUR_SIZE_MESSAGE]
    assert forms[1].errors["size"] == [SHARED_STOCK_COLOUR_SIZE_MESSAGE]


def test_ticking_shared_stock_with_colours(admin_client, product):
    # e.g. T-shirts in different colours can't share stock
    black = baker.make(ProductVariant, product=product, colour="Black", stock=1)
    white = baker.make(ProductVariant, product=product, colour="White", stock=1)
    product.shares_stock = True
    data = product_form_data(product, [black, white], stock="5", stock_shown="0")
    resp = admin_client.post(edit_url(product), data)
    assert resp.status_code == 200
    product.refresh_from_db()
    assert not product.shares_stock


def test_variant_page_shared_stock_colour(admin_client, cards, pack):
    data = variant_form_data(pack)
    data["colour"] = "Red"
    resp = admin_client.post(variant_edit_url(pack), data)
    assert resp.status_code == 200
    assert resp.context["form"].errors["colour"] == [SHARED_STOCK_COLOUR_SIZE_MESSAGE]


def test_admin_variants_list(admin_client, cards, single, pack):
    content = admin_client.get(reverse("wagtailsnippets_shop_productvariant:list")).content.decode()
    assert "13 (shared stock)" in content
    assert "2 packs (from 13 shared)" in content


def test_admin_pack_size_at_least_1(admin_client, cards, single):
    data = product_form_data(cards, [single])
    data["variants-0-pack_size"] = "0"
    resp = admin_client.post(edit_url(cards), data)
    assert resp.status_code == 200
    single.refresh_from_db()
    assert single.pack_size == 1


# Items per pack without shared stock


def test_admin_pack_size_needs_shared_stock(admin_client, product):
    single = baker.make(ProductVariant, product=product, variant_name="Single", stock=5, price=2)
    pack = baker.make(ProductVariant, product=product, variant_name="Pack of 3", stock=5, price=5)
    data = product_form_data(product, [single, pack])
    data["variants-1-pack_size"] = "3"
    resp = admin_client.post(edit_url(product), data)
    assert resp.status_code == 200
    content = html.unescape(resp.content.decode())
    assert PACK_SIZE_NOT_SHARED_MESSAGE in content
    pack.refresh_from_db()
    assert pack.pack_size == 1


def test_admin_pack_size_deleted_variant(admin_client, product):
    # a variant being deleted isn't checked
    single = baker.make(ProductVariant, product=product, variant_name="Single", stock=5, price=2)
    pack = baker.make(ProductVariant, product=product, variant_name="Pack of 3", stock=5, price=5)
    data = product_form_data(product, [single, pack])
    data["variants-1-pack_size"] = "3"
    data["variants-1-DELETE"] = "on"
    resp = admin_client.post(edit_url(product), data)
    assert resp.status_code == 302
    assert not ProductVariant.objects.filter(id=pack.id).exists()


def variant_form_data(variant, **data):
    return {
        "product": str(variant.product_id),
        "variant_name": variant.variant_name,
        "price": str(variant.price),
        "stock": str(variant.stock),
        "stock_shown": str(variant.stock),
        "pack_size": str(variant.pack_size),
        "live": "on",
        **data,
    }


def test_variant_page_pack_size_needs_shared_stock(admin_client, product):
    variant = baker.make(ProductVariant, product=product, variant_name="Pack", stock=5, price=5)
    resp = admin_client.post(variant_edit_url(variant), variant_form_data(variant, pack_size="3"))
    assert resp.status_code == 200
    assert PACK_SIZE_NOT_SHARED_MESSAGE in html.unescape(resp.content.decode())
    variant.refresh_from_db()
    assert variant.pack_size == 1


def test_variant_page_pack_size_shared_stock(admin_client, cards, pack):
    data = variant_form_data(pack, pack_size="4")
    del data["stock"], data["stock_shown"]
    resp = admin_client.post(variant_edit_url(pack), data)
    assert resp.status_code == 302
    pack.refresh_from_db()
    assert pack.pack_size == 4


def test_pack_size_constraint(cards, pack):
    # stock calculations divide by the pack size
    pack.pack_size = 0
    with pytest.raises(IntegrityError), transaction.atomic():
        pack.save()


# Variants that aren't live, and making them live


def test_stock_display_not_live(cards, single, pack, product):
    single.live = pack.live = False
    assert single.stock_display() == "13 (shared stock, not live)"
    assert pack.stock_display() == "2 packs (from 13 shared, not live)"
    other = baker.make(ProductVariant, product=baker.make("shop.Product", category=cards.category), stock=10, live=False)
    assert other.stock_display() == "10 (not live)"


def messages_for(resp):
    return [str(m) for m in get_messages(resp.wsgi_request)]


def test_product_page_variant_made_live(admin_client, product):
    # stock left from before it was taken off sale
    single = baker.make(ProductVariant, product=product, variant_name="Single", stock=10, price=2, live=False)
    resp = admin_client.post(edit_url(product), product_form_data(product, [single]))
    assert resp.status_code == 302
    assert "Test Product - Single is now live with 10 in stock. Check that's still right." in messages_for(resp)


def test_product_page_variant_made_live_shared_stock(admin_client, cards, single, pack):
    pack.live = False
    pack.save()
    resp = admin_client.post(edit_url(cards), product_form_data(cards, [single, pack]))
    assert (
        "Test Product - Pack of 5 is now live, sold from the product's shared stock "
        "of 13. Check that's still right."
    ) in messages_for(resp)
    # the single was already live
    assert not any("Single is now live" in message for message in messages_for(resp))


@pytest.mark.parametrize("stock", [0, -1])
def test_product_page_variant_made_live_no_stock(admin_client, product, stock):
    single = baker.make(ProductVariant, product=product, variant_name="Single", stock=stock, price=2, live=False)
    resp = admin_client.post(edit_url(product), product_form_data(product, [single]))
    assert not any("is now live" in message for message in messages_for(resp))


def test_product_page_shared_stock_none_left(admin_client, cards, single, pack):
    cards.stock = 4
    cards.save()
    pack.live = False
    pack.save()
    resp = admin_client.post(edit_url(cards), product_form_data(cards, [single, pack]))
    # not enough for a pack
    assert not any("is now live" in message for message in messages_for(resp))


def test_product_page_new_or_deleted_variants(admin_client, product):
    # a new live variant (its stock has just been entered), and a variant being
    # deleted, aren't reminded about
    old = baker.make(ProductVariant, product=product, variant_name="Old", stock=10, price=2, live=False)
    data = product_form_data(product, [old])
    data["variants-0-DELETE"] = "on"
    data.update(
        {
            "variants-TOTAL_FORMS": "2",
            "variants-1-variant_name": "New",
            "variants-1-price": "3",
            "variants-1-stock": "5",
            "variants-1-pack_size": "1",
            "variants-1-live": "on",
            "variants-1-ORDER": "2",
        }
    )
    resp = admin_client.post(edit_url(product), data)
    assert resp.status_code == 302
    assert not any("is now live" in message for message in messages_for(resp))


def test_variant_page_made_live(admin_client, product):
    variant = baker.make(ProductVariant, product=product, variant_name="Pack", stock=7, price=5, live=False)
    resp = admin_client.post(variant_edit_url(variant), variant_form_data(variant, live="on"))
    assert resp.status_code == 302
    assert "Test Product - Pack is now live with 7 in stock. Check that's still right." in messages_for(resp)
    # the reminder is shown on the next page
    reminder = "Test Product - Pack is now live with 7 in stock."
    assert reminder in html.unescape(admin_client.get(resp.url).content.decode())
    # saving it again (already live) doesn't remind
    variant.refresh_from_db()
    resp = admin_client.post(variant_edit_url(variant), variant_form_data(variant))
    assert not any("is now live" in message for message in messages_for(resp))


def test_check_pack_sizes_without_variants():
    # (e.g. a product form without the variants formset)
    from types import SimpleNamespace

    from ..models import ProductAdminForm

    assert ProductAdminForm._check_pack_sizes(SimpleNamespace(formsets={}), {}) is None
