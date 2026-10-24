"""
Dispatchers, and shipping (or collecting) an order's items: per-item status,
the order's status, and the customer's emails.
"""
from datetime import UTC, datetime
from smtplib import SMTPException

import html

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from ..models import DISPATCHERS_GROUP, OrderItem, dispatcher_name, is_dispatcher
from ..status import OrderStatus

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")


def make_dispatcher(first_name, email):
    user = baker.make(
        "auth.User", first_name=first_name, last_name="Smith", email=email
    )
    user.groups.add(Group.objects.get_or_create(name=DISPATCHERS_GROUP)[0])
    return user


@pytest.fixture
def dispatcher():
    """A user in the Dispatchers group"""
    return make_dispatcher("Ann", "ann@test.com")


@pytest.fixture
def shop_variants(product, dispatcher):
    """A mug (sent by Ann), a card (no dispatcher) and a raffle ticket (not shipped)"""
    product.dispatcher = dispatcher
    product.save()
    mug = baker.make("shop.ProductVariant", product=product, variant_name="Mug", price=10, stock=10)
    card_product = baker.make("shop.Product", category=product.category, name="Card", price=2)
    card = baker.make("shop.ProductVariant", product=card_product, price=2, stock=10)
    raffle_product = baker.make(
        "shop.Product",
        category=product.category,
        name="Raffle ticket",
        price=1,
        requires_shipping=False,
    )
    raffle = baker.make("shop.ProductVariant", product=raffle_product, price=1, stock=10)
    return mug, card, raffle


def make_order(variants, shipping_method="deliver", status=OrderStatus.PROCESSING):
    basket = baker.make(Basket, shipping_method=shipping_method, extra={"email": "c@test.com"})
    for variant in variants:
        basket.add(variant, quantity=2)
    order = Order.objects.create_from_basket(basket, None, status=status)
    mail.outbox.clear()
    return order


def item_for(order, variant):
    return order.items.get(product_id=variant.id)


# Order items


def test_order_items_dispatcher_and_status(shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    assert (item_for(order, mug).dispatcher, item_for(order, mug).shipping_status) == (
        dispatcher,
        OrderItem.TO_SEND,
    )
    assert (item_for(order, card).dispatcher, item_for(order, card).shipping_status) == (
        None,
        OrderItem.TO_SEND,
    )
    assert item_for(order, raffle).shipping_status == OrderItem.NO_SHIPPING
    assert not item_for(order, raffle).needs_shipping
    assert item_for(order, mug).needs_shipping
    # reassigning the product later doesn't change the order
    mug.product.dispatcher = make_dispatcher("Bob", "bob@test.com")
    mug.product.save()
    assert item_for(order, mug).dispatcher == dispatcher
    assert item_for(order, mug).dispatcher_name == "Ann Smith"
    assert item_for(order, card).dispatcher_name == ""


def test_shipping_status_label():
    assert OrderItem(shipping_status=OrderItem.SHIPPED).get_shipping_status_display() == (
        "Shipped/collected"
    )


# Orders with nothing to ship


def test_order_nothing_to_ship_completed(shop_variants, django_capture_on_commit_callbacks):
    _, _, raffle = shop_variants
    basket = baker.make(Basket, extra={"email": "c@test.com"})
    basket.add(raffle)
    with django_capture_on_commit_callbacks(execute=True):
        order = Order.objects.create_from_basket(basket, None, status=OrderStatus.PROCESSING)
    assert order.status == OrderStatus.COMPLETED
    # one email (the order received email), saying it's complete
    (email,) = mail.outbox
    assert email.subject == f"Order '{order.ref}' has been received"
    assert "Your order is complete." in email.body


@pytest.mark.parametrize("status", [OrderStatus.HOLD, OrderStatus.CREATED])
def test_unpaid_order_nothing_to_ship_not_completed(shop_variants, status):
    _, _, raffle = shop_variants
    order = make_order([raffle], status=status)
    assert order.status == status


def test_mixed_order_processing(shop_variants):
    order = make_order(shop_variants)
    assert order.status == OrderStatus.PROCESSING


# Shipping items


def test_ship_some_items(shop_variants, dispatcher, freezer, django_capture_on_commit_callbacks):
    freezer.move_to("2026-10-21 10:00")
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    with django_capture_on_commit_callbacks(execute=True):
        shipped = order.mark_items_shipped([item_for(order, mug)], dispatcher)
    assert shipped == [item_for(order, mug)]
    mug_item = item_for(order, mug)
    assert (mug_item.shipping_status, mug_item.shipped_at, mug_item.shipped_by) == (
        OrderItem.SHIPPED,
        datetime(2026, 10, 21, 10, tzinfo=UTC),
        dispatcher,
    )
    order.refresh_from_db()
    assert order.status == OrderStatus.PARTIALLY_SHIPPED
    (email,) = mail.outbox
    assert email.to == ["c@test.com"]
    assert email.subject == f"Part of order '{order.ref}' has been shipped"
    assert email.body.startswith(
        "These items from your order have been shipped:\n"
        "- 2 x Test Product - Mug\n"
        "\n"
        "Still to be shipped:\n"
        "- 2 x Card\n"
        "\n"
        "View the status of your order: https://"
    )


def test_ship_rest_of_items(shop_variants, dispatcher, django_capture_on_commit_callbacks):
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    order.mark_items_shipped([item_for(order, mug)], dispatcher)
    with django_capture_on_commit_callbacks(execute=True):
        order.mark_items_shipped([item_for(order, card)], dispatcher)
    order.refresh_from_db()
    # shipped, not completed (completed is set by hand)
    assert order.status == OrderStatus.SHIPPED
    (email,) = mail.outbox
    assert email.subject == f"Order '{order.ref}' has been shipped"
    assert "- 2 x Card" in email.body
    assert "Still to be" not in email.body


def test_ship_all_items_at_once(shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    shipped = order.mark_items_shipped(list(order.items.all()), dispatcher)
    # the raffle ticket doesn't need shipping
    assert {item.product_id for item in shipped} == {mug.id, card.id}
    order.refresh_from_db()
    assert order.status == OrderStatus.SHIPPED


def test_collect_items(shop_variants, dispatcher, django_capture_on_commit_callbacks):
    mug, card, raffle = shop_variants
    order = make_order(shop_variants, shipping_method="collect")
    with django_capture_on_commit_callbacks(execute=True):
        order.mark_items_shipped([item_for(order, mug)], dispatcher)
    order.refresh_from_db()
    assert order.status == OrderStatus.PARTIALLY_SHIPPED
    (email,) = mail.outbox
    assert email.subject == f"Part of order '{order.ref}' has been collected"
    assert "These items from your order have been collected:" in email.body
    assert "Still to be collected:" in email.body


def test_ship_items_already_shipped(shop_variants, dispatcher, django_capture_on_commit_callbacks):
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    order.mark_items_shipped([item_for(order, mug)], dispatcher)
    with django_capture_on_commit_callbacks(execute=True):
        # e.g. two dispatchers, or a double click
        assert order.mark_items_shipped([item_for(order, mug)], dispatcher) == []
        assert order.mark_items_shipped([item_for(order, raffle)], dispatcher) == []
    assert mail.outbox == []


def test_ship_another_orders_items(shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    other = make_order([mug])
    assert order.mark_items_shipped([item_for(other, mug)], dispatcher) == []
    assert item_for(other, mug).shipping_status == OrderItem.TO_SEND


@pytest.mark.parametrize(
    "status", [OrderStatus.REFUNDED, OrderStatus.HOLD, OrderStatus.SHIPPED, OrderStatus.COMPLETED]
)
def test_ship_items_status_unchanged(shop_variants, dispatcher, status):
    # e.g. a refunded order, or one already marked shipped or completed by hand
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    Order.objects.filter(pk=order.pk).update(status=status)
    order.refresh_from_db()
    order.mark_items_shipped([item_for(order, mug)], dispatcher)
    order.refresh_from_db()
    assert order.status == status


# Statuses


def test_status_transitions(order):
    order.status = OrderStatus.PROCESSING
    assert OrderStatus.validate_transition(OrderStatus.PARTIALLY_SHIPPED, order)
    order.status = OrderStatus.PARTIALLY_SHIPPED
    assert OrderStatus.validate_transition(OrderStatus.SHIPPED, order)
    assert OrderStatus.validate_transition(OrderStatus.REFUNDED, order)
    with pytest.raises(ValidationError):
        OrderStatus.validate_transition(OrderStatus.PROCESSING, order)
    assert OrderStatus.get_payable() == ["CREATED", "HOLD", "FAILED"]
    assert OrderStatus.PARTIALLY_SHIPPED.label == "Partially shipped"


# Dispatchers


def test_dispatcher(dispatcher):
    assert is_dispatcher(dispatcher)
    assert not is_dispatcher(baker.make("auth.User"))
    assert not is_dispatcher(None)
    assert dispatcher_name(dispatcher) == "Ann Smith"
    assert dispatcher_name(baker.make("auth.User", username="bob")) == "bob"


def test_dispatcher_deleted(shop_variants, dispatcher):
    # the order item keeps the dispatcher's name
    mug, card, raffle = shop_variants
    order = make_order(shop_variants)
    dispatcher.delete()
    item = item_for(order, mug)
    assert (item.dispatcher, item.dispatcher_name) == (None, "Ann Smith")


def test_dispatcher_removed_from_group(shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    product = mug.product
    assert product.dispatcher_warning is None
    assert product.dispatcher_display() == "Ann Smith"
    dispatcher.groups.clear()
    assert product.dispatcher_warning == (
        "Ann Smith isn't in the Dispatchers group any more. Choose another dispatcher."
    )
    assert "shop-dispatcher-warning" in product.dispatcher_display()
    assert card.product.dispatcher_display() == ""


def test_dispatcher_display_emailed(shop_variants, dispatcher):
    # an email icon if the dispatcher is emailed about new orders
    product = shop_variants[0].product
    assert "shop-dispatcher-emailed" not in product.dispatcher_display()
    product.notify_dispatcher = True
    display = product.dispatcher_display()
    assert display.startswith("Ann Smith <span title=\"Emailed about new orders\">")
    assert '<use href="#icon-mail">' in display
    assert '<span class="w-sr-only">Emailed about new orders</span>' in display
    # and the warning too, if they're not a dispatcher any more
    dispatcher.groups.clear()
    display = product.dispatcher_display()
    assert display.index("shop-dispatcher-emailed") < display.index("shop-dispatcher-warning")


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    return client


DISPATCHERS_URL = "/admin/shop_dispatchers/"


def test_admin_dispatchers_page(admin_client, dispatcher, product):
    product.dispatcher = dispatcher
    product.save()
    baker.make("auth.User", first_name="Cat", last_name="Lee", email="cat@test.com")
    resp = admin_client.get(reverse("shop_dispatchers:index"))
    assert reverse("shop_dispatchers:index") == DISPATCHERS_URL
    content = html.unescape(resp.content.decode())
    # the dispatchers, with how many products they dispatch
    assert [(d, d.product_count) for d in resp.context["dispatchers"]] == [(dispatcher, 1)]
    assert reverse("wagtailusers_users:edit", args=(dispatcher.pk,)) in content
    assert f'name="remove" value="{dispatcher.pk}"' in content
    # users who aren't dispatchers can be added
    choices = [label for _, label in resp.context["form"].fields["user"].choices]
    assert "Cat Lee (cat@test.com)" in choices
    assert "Ann Smith (ann@test.com)" not in choices
    assert "Shop Stock" in content


def test_admin_dispatchers_page_empty(admin_client):
    content = admin_client.get(DISPATCHERS_URL).content.decode()
    assert "There are no dispatchers yet." in content


def messages_for(resp):
    # Wagtail admin messages are rendered as HTML
    return [html.unescape(str(m)).strip() for m in get_messages(resp.wsgi_request)]


def test_admin_add_dispatcher(admin_client):
    user = baker.make("auth.User", username="cat")
    resp = admin_client.post(DISPATCHERS_URL, {"user": user.pk})
    assert resp.url == DISPATCHERS_URL
    assert is_dispatcher(user)
    assert messages_for(resp) == ["cat is now a dispatcher."]
    # the user's name (no email) in the choices
    form_choices = admin_client.get(DISPATCHERS_URL).context["form"].fields["user"].choices
    assert "cat" not in [label for _, label in form_choices]


def test_admin_add_dispatcher_invalid(admin_client, dispatcher):
    # e.g. already a dispatcher
    resp = admin_client.post(DISPATCHERS_URL, {"user": dispatcher.pk})
    assert resp.status_code == 200
    assert "user" in resp.context["form"].errors


def test_admin_remove_dispatcher(admin_client, dispatcher):
    resp = admin_client.post(DISPATCHERS_URL, {"remove": dispatcher.pk})
    assert resp.url == DISPATCHERS_URL
    assert not is_dispatcher(dispatcher)
    assert messages_for(resp) == ["Ann Smith isn't a dispatcher any more."]


@pytest.mark.parametrize("products,text", [(1, "1 product still has them"), (2, "2 products still have them")])
def test_admin_remove_dispatcher_with_products(admin_client, dispatcher, product, products, text):
    for _ in range(products):
        baker.make("shop.Product", category=product.category, dispatcher=dispatcher)
    resp = admin_client.post(DISPATCHERS_URL, {"remove": dispatcher.pk})
    (message,) = messages_for(resp)
    assert message.startswith(f"Ann Smith isn't a dispatcher any more. {text} as dispatcher")


def test_admin_remove_not_a_dispatcher(admin_client):
    user = baker.make("auth.User")
    assert admin_client.post(DISPATCHERS_URL, {"remove": user.pk}).status_code == 404


def test_admin_dispatchers_needs_permission(client):
    # e.g. an admin user who can't change users: Wagtail sends them to the
    # dashboard, with a message
    user = baker.make("auth.User")
    user.user_permissions.add(Permission.objects.get(codename="access_admin"))
    client.force_login(user)
    resp = client.get(DISPATCHERS_URL)
    assert resp.url == "/admin/"
    assert client.post(DISPATCHERS_URL, {"user": user.pk}).url == "/admin/"
    assert not is_dispatcher(user)


def test_admin_product_dispatcher(admin_client, dispatcher, product):
    product.dispatcher = dispatcher
    product.save()
    url = reverse("wagtailsnippets_shop_product:edit", args=(product.id,))
    content = admin_client.get(url).content.decode()
    assert 'name="notify_dispatcher"' in content
    # only users in the Dispatchers group can be chosen, by name
    form = admin_client.get(url).context["form"]
    assert list(form.fields["dispatcher"].queryset) == [dispatcher]
    assert list(form.fields["dispatcher"].choices)[1][1] == "Ann Smith"
    assert "isn't in the Dispatchers group" not in content
    # the products list shows each product's dispatcher
    content = admin_client.get(reverse("wagtailsnippets_shop_product:list")).content.decode()
    assert "Ann Smith" in content
    assert "shop-dispatcher-warning" not in content


def test_admin_product_dispatcher_not_in_group(admin_client, dispatcher, product):
    product.dispatcher = dispatcher
    product.save()
    dispatcher.groups.clear()
    url = reverse("wagtailsnippets_shop_product:edit", args=(product.id,))
    resp = admin_client.get(url)
    content = html.unescape(resp.content.decode())
    assert "Ann Smith isn't in the Dispatchers group any more. Choose another dispatcher." in content
    # still the product's dispatcher (a choice for this product only), so saving
    # doesn't remove them
    assert list(resp.context["form"].fields["dispatcher"].queryset) == [dispatcher]
    other = baker.make("shop.Product", category=product.category)
    other_form = admin_client.get(
        reverse("wagtailsnippets_shop_product:edit", args=(other.id,))
    ).context["form"]
    assert list(other_form.fields["dispatcher"].queryset) == []
    content = admin_client.get(reverse("wagtailsnippets_shop_product:list")).content.decode()
    assert "shop-dispatcher-warning" in content


def test_update_shipping_status_nothing_shipped(shop_variants):
    order = make_order(shop_variants)
    order.update_shipping_status()
    order.refresh_from_db()
    assert order.status == OrderStatus.PROCESSING


# Emailing dispatchers about new orders


@pytest.fixture
def notified_dispatcher(dispatcher, product):
    # the mug's product emails its dispatcher about new orders
    product.notify_dispatcher = True
    product.save()
    return dispatcher


def emails_to(address):
    return [email for email in mail.outbox if email.to == [address]]


def paid_order(variants, django_capture_on_commit_callbacks, shipping_method="deliver", status=OrderStatus.PROCESSING):
    basket = baker.make(
        Basket,
        shipping_method=shipping_method,
        extra={"email": "c@test.com", "name": "Cat", "shipping_address": "1 Road\nTown"},
    )
    for variant in variants:
        basket.add(variant, quantity=2)
    with django_capture_on_commit_callbacks(execute=True):
        return Order.objects.create_from_basket(basket, None, status=status)


def test_dispatcher_emailed_about_paid_order(
    shop_variants, notified_dispatcher, django_capture_on_commit_callbacks
):
    order = paid_order(shop_variants, django_capture_on_commit_callbacks)
    (email,) = emails_to("ann@test.com")
    assert email.subject == f"Shop order '{order.ref}': items to send"
    # only their items (not the card, which has no dispatcher, or the raffle
    # ticket, which isn't shipped)
    assert email.body == (
        f"Shop order '{order.ref}' has items for you to send:\n"
        "- 2 x Test Product - Mug\n"
        "\n"
        "Customer: Cat (c@test.com)\n"
        "Shipping address:\n"
        "1 Road\n"
        "Town"
    )


def test_dispatcher_emailed_about_collection(
    shop_variants, notified_dispatcher, django_capture_on_commit_callbacks
):
    order = paid_order(shop_variants, django_capture_on_commit_callbacks, shipping_method="collect")
    (email,) = emails_to("ann@test.com")
    assert email.subject == f"Shop order '{order.ref}': items to hand over"
    assert "has items for you to hand over (for collection):" in email.body
    assert email.body.endswith("Shipping method: Collect in person")


def test_dispatcher_not_emailed(shop_variants, dispatcher, django_capture_on_commit_callbacks):
    # dispatchers aren't emailed unless the product is set to email them
    paid_order(shop_variants, django_capture_on_commit_callbacks)
    assert emails_to("ann@test.com") == []


def test_dispatcher_emailed_only_for_products_set_to(
    shop_variants, notified_dispatcher, django_capture_on_commit_callbacks
):
    # another of Ann's products, not set to email her
    mug, card, raffle = shop_variants
    card.product.dispatcher = notified_dispatcher
    card.product.save()
    paid_order(shop_variants, django_capture_on_commit_callbacks)
    (email,) = emails_to("ann@test.com")
    assert "Mug" in email.body
    assert "Card" not in email.body


def test_dispatcher_emailed_when_order_paid_later(
    shop_variants, notified_dispatcher, django_capture_on_commit_callbacks
):
    order = paid_order(shop_variants, django_capture_on_commit_callbacks, status=OrderStatus.HOLD)
    assert emails_to("ann@test.com") == []
    with django_capture_on_commit_callbacks(execute=True):
        order.status = OrderStatus.PROCESSING
        order.save()
    assert len(emails_to("ann@test.com")) == 1


def test_dispatcher_email_failure_logged(
    shop_variants, notified_dispatcher, django_capture_on_commit_callbacks, caplog, monkeypatch
):
    def fail(self, *args, **kwargs):
        raise SMTPException("Down")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", fail)
    order = paid_order(shop_variants, django_capture_on_commit_callbacks)
    assert f"Error sending email 'Shop order '{order.ref}': items to send'" in caplog.text


def test_notify_dispatcher_needs_dispatcher(product, dispatcher):
    product.notify_dispatcher = True
    with pytest.raises(ValidationError) as e:
        product.clean()
    assert e.value.message_dict == {"notify_dispatcher": ["Choose a dispatcher to email."]}
    product.dispatcher = dispatcher
    product.clean()


def test_notify_dispatcher_needs_email(product, dispatcher):
    dispatcher.email = ""
    product.dispatcher = dispatcher
    product.notify_dispatcher = True
    with pytest.raises(ValidationError) as e:
        product.clean()
    assert e.value.message_dict == {"notify_dispatcher": ["Ann Smith has no email address."]}


# The shop's new order email


@pytest.fixture
def notify_settings():
    baker.make("shop.ShopSettings", notify_email_addresses="shop@test.com")


def shop_email():
    (email,) = emails_to("shop@test.com")
    return email


def test_shop_new_order_email(
    shop_variants, notified_dispatcher, notify_settings, django_capture_on_commit_callbacks
):
    # (processing, but no payment recorded, e.g. in the admin)
    order = paid_order(shop_variants, django_capture_on_commit_callbacks)
    email = shop_email()
    assert email.subject == f"New shop order '{order.ref}'"
    assert email.body == (
        f"A new shop order '{order.ref}' has been received (not paid).\n"
        "Some items' dispatchers haven't been emailed (or there isn't one): please pass these on.\n"
        "\n"
        "Customer: Cat (c@test.com)\n"
        "Shipping method: Delivery\n"
        "Shipping address:\n"
        "1 Road\n"
        "Town\n"
        "\n"
        "Items:\n"
        "- 2 x Test Product - Mug: Ann Smith (emailed)\n"
        "- 2 x Card: no dispatcher\n"
        "- 2 x Raffle ticket: no shipping needed\n"
        "\n"
        f"Total: £{order.total:.2f}\n"
        "\n"
        f"View the order: https://podencosinneed.org/admin/shop/orders/{order.pk}/"
    )


def test_shop_new_order_email_paid_all_emailed(
    shop_variants, notified_dispatcher, notify_settings, django_capture_on_commit_callbacks
):
    # paid (e.g. a free order with a discount code), collected, and its only
    # item's dispatcher is emailed: nothing to pass on
    mug, card, raffle = shop_variants
    basket = baker.make(
        Basket, shipping_method="collect", extra={"email": "c@test.com", "name": "Cat"}
    )
    basket.add(mug)
    code = baker.make("shop.DiscountCode", code="FREE", amount=50)
    basket.set_discount_code(code)
    with django_capture_on_commit_callbacks(execute=True):
        order = Order.objects.create_from_basket(basket, None, status=OrderStatus.PROCESSING)
    body = shop_email().body
    assert body.startswith(f"A new shop order '{order.ref}' has been received (paid).\n\n")
    assert "please pass these on" not in body
    assert "Shipping method: Collect in person\n\nItems:" in body
    # the mug (£10) is free
    assert "Discount code: FREE (-£10.00)\nTotal: £0.00 (including discount)" in body


def test_shop_new_order_email_awaiting_payment(
    shop_variants, dispatcher, notify_settings, django_capture_on_commit_callbacks
):
    order = paid_order(shop_variants, django_capture_on_commit_callbacks, status=OrderStatus.HOLD)
    body = shop_email().body
    assert body.startswith(f"A new shop order '{order.ref}' has been received (awaiting payment).")
    # Ann isn't emailed about this product
    assert "- 2 x Test Product - Mug: Ann Smith (not emailed)" in body
    assert "please pass these on" in body
