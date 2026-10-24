"""
The dispatcher view (shop/admin_dispatch.py): dispatchers' own items to send,
grouped by order, marking an order's items shipped, the items they've sent, and
the download.
"""

import html
import io
import re
from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core import mail
from django.urls import reverse
from model_bakery import baker
from openpyxl import load_workbook

from ..models import OrderItem
from ..status import OrderStatus
from .test_shipping import dispatcher, make_dispatcher, make_order, shop_variants  # noqa: F401

pytestmark = pytest.mark.django_db

URL = reverse("shop_dispatch:index")


@pytest.fixture
def dispatcher_client(client, dispatcher):
    client.force_login(dispatcher)
    return client


def content(resp):
    return html.unescape(resp.content.decode())


def messages_for(resp):
    return [html.unescape(str(m)).strip() for m in get_messages(resp.wsgi_request)]


def order_with(variants, **kwargs):
    order = make_order(variants, **kwargs)
    order.name = "Cat"
    order.shipping_address = "1 Road\nTown"
    order.save()
    return order


def test_dispatchers_group_can_use_admin(dispatcher):
    assert dispatcher.has_perm("wagtailadmin.access_admin")


def test_dispatcher_starts_at_orders_to_send(dispatcher_client):
    # their only admin page
    assert dispatcher_client.get(reverse("wagtailadmin_home")).url == URL


def test_orders_to_send(dispatcher_client, shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    newer = order_with([mug], shipping_method="collect")
    older = order_with([mug, card, raffle])
    # not: unpaid orders, other dispatchers' items, or items already sent
    make_order([mug], status=OrderStatus.HOLD)
    bob = make_dispatcher("Bob", "bob@test.com")
    bobs = make_order([card])
    OrderItem.objects.filter(order=bobs).update(dispatcher=bob)
    shipped = make_order([mug])
    shipped.mark_items_shipped(shipped.items.all(), dispatcher)
    # (dated after making the orders: salesman numbers orders from the latest)
    Order = type(older)
    Order.objects.filter(pk=older.pk).update(date_created=datetime(2026, 10, 1, 12, tzinfo=UTC))
    Order.objects.filter(pk=newer.pk).update(date_created=datetime(2026, 10, 2, 12, tzinfo=UTC))

    resp = dispatcher_client.get(URL)
    assert resp.status_code == 200
    # oldest first, only their items
    assert [(order, [item.name for item in items]) for order, items in resp.context["orders"]] == [
        (older, ["Test Product - Mug"]),
        (newer, ["Test Product - Mug"]),
    ]
    page = content(resp)
    assert "<title>Items to send" in page
    nav = re.search(r'<nav[^>]*aria-label="Breadcrumb">(.*?)</nav>', page, re.S).group(1)
    assert "Items to send" in " ".join(re.sub(r"<[^>]+>", " ", nav).split())
    assert "To send (2)" in page
    assert f"Order {older.ref}" in page
    assert "1 Road<br>Town" in page
    assert "2 x</strong> Test Product - Mug" in page
    assert "Mark as shipped" in page
    # collections: the customer's email, not an address
    assert "Mark as collected" in page
    assert 'href="mailto:c@test.com"' in page


def test_nothing_to_send(dispatcher_client):
    page = content(dispatcher_client.get(URL))
    assert "Nothing to send at the moment." in page
    assert "Download (Excel)" not in page


def test_mark_order_shipped(dispatcher_client, shop_variants, dispatcher, django_capture_on_commit_callbacks):
    mug, card, raffle = shop_variants
    order = order_with([mug, card])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        resp = dispatcher_client.post(URL, {"order": order.pk})
    assert resp.url == URL
    assert messages_for(resp) == [
        f"Order {order.ref}: 1 item marked shipped, and the customer has been emailed."
    ]
    # only their item: the card (no dispatcher) is still to send
    mug_item = order.items.get(product_id=mug.id)
    assert mug_item.shipping_status == OrderItem.SHIPPED
    assert mug_item.shipped_by == dispatcher
    assert order.items.get(product_id=card.id).shipping_status == OrderItem.TO_SEND
    order.refresh_from_db()
    assert order.status == OrderStatus.PARTIALLY_SHIPPED
    assert len(mail.outbox) == 1


def test_mark_collected(dispatcher_client, shop_variants):
    mug, card, raffle = shop_variants
    order = order_with([mug], shipping_method="collect")
    resp = dispatcher_client.post(URL, {"order": order.pk})
    assert messages_for(resp) == [
        f"Order {order.ref}: 1 item marked collected, and the customer has been emailed."
    ]


def test_mark_other_dispatchers_order(dispatcher_client, shop_variants):
    # nothing of theirs to send (e.g. another dispatcher's, or already sent)
    mug, card, raffle = shop_variants
    order = order_with([card])
    resp = dispatcher_client.post(URL, {"order": order.pk})
    assert messages_for(resp) == [f"Order {order.ref} has nothing for you to send."]
    assert order.items.get().shipping_status == OrderItem.TO_SEND


def test_sent(dispatcher_client, shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    order = order_with([mug])
    order.mark_items_shipped(order.items.all(), dispatcher)
    order.items.update(shipped_at=datetime(2026, 10, 1, 12, tzinfo=UTC))
    # shipped by someone else (e.g. a shop admin) for them
    other = order_with([mug])
    other.mark_items_shipped(other.items.all(), baker.make("auth.User", first_name="Sam"))
    order_with([mug])  # still to send
    resp = dispatcher_client.get(URL, {"sent": ""})
    assert [order for order, items in resp.context["orders"]] == [other, order]
    page = content(resp)
    assert "Shipped 1 Oct 2026" in page
    assert "by Sam" in page
    assert "Mark as shipped" not in page
    assert "To send (1)" in page


def test_nothing_sent(dispatcher_client):
    assert "You haven't sent anything yet." in content(dispatcher_client.get(URL, {"sent": ""}))


def test_download(dispatcher_client, shop_variants, freezer):
    freezer.move_to(datetime(2026, 10, 24, 14, 5, tzinfo=UTC))
    mug, card, raffle = shop_variants
    first, second = order_with([mug]), order_with([mug])
    resp = dispatcher_client.get(URL, {"export": "xlsx"})
    assert 'filename="items-to-send-2026-10-24-1405.xlsx"' in resp["Content-Disposition"]
    sheet = load_workbook(io.BytesIO(b"".join(resp.streaming_content))).active
    assert sheet.title == "Items to send"
    rows = list(sheet.values)
    assert rows[0] == (
        "Order", "Date", "Customer", "Email", "Shipping method", "Shipping address", "Item", "Quantity",
    )
    assert [row[0] for row in rows[1:]] == [first.ref, second.ref]
    assert rows[1][2:] == ("Cat", "c@test.com", "Delivery", "1 Road\nTown", "Test Product - Mug", 2)
    # (each order shaded in turn)
    assert sheet["A2"].fill.fill_type == "solid"
    assert sheet["A3"].fill.fill_type is None


def test_not_for_other_users(client):
    # e.g. shop admins who aren't dispatchers
    user = baker.make("auth.User")
    user.groups.add(Group.objects.get(name="Shop admins"))
    client.force_login(user)
    assert client.get(URL).url == reverse("wagtailadmin_home")
    content = client.get(reverse("shop_orders:index")).content.decode()
    assert '"items-to-send"' not in content


def test_superusers_can_see_it(client):
    # (but it isn't in their menu, as they're not dispatchers)
    client.force_login(baker.make("auth.User", is_superuser=True))
    resp = client.get(URL)
    assert resp.status_code == 200
    assert '"items-to-send"' not in resp.content.decode()


def test_dispatcher_menu(dispatcher_client):
    page = dispatcher_client.get(URL).content.decode()
    names = re.findall(r'"name": "([a-z-]+)", "label"', page)
    # (and the account menu)
    assert [name for name in names if name not in ("account", "logout")] == ["items-to-send"]


# Seeing a dispatcher's page (read-only), e.g. from the Dispatchers page


def shop_admin(client):
    user = baker.make("auth.User")
    user.groups.add(Group.objects.get(name="Shop admins"))
    client.force_login(user)
    return user


def test_see_dispatchers_orders(client, shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    order = order_with([mug])
    shop_admin(client)
    url = f"{URL}?dispatcher={dispatcher.pk}"
    resp = client.get(url)
    assert resp.status_code == 200
    assert [o for o, items in resp.context["orders"]] == [order]
    page = content(resp)
    assert "<title>Ann Smith's items to send" in page
    assert "Ann Smith's items to send, as they see them" in page
    assert "Your items to send" not in page
    # read-only: no marking shipped, but a link to the order's page
    assert "Mark as shipped" not in page
    assert reverse("shop_orders:edit", args=(order.pk,)) in page
    # the tabs and download stay on their page
    assert f'href="{URL}?dispatcher={dispatcher.pk}&amp;sent"' in resp.content.decode()
    assert f"{URL}?dispatcher={dispatcher.pk}&amp;export=xlsx" in resp.content.decode()
    resp = client.get(URL, {"dispatcher": dispatcher.pk, "export": "xlsx"})
    assert "items-to-send" in resp["Content-Disposition"]
    # breadcrumbs: back to the Dispatchers page
    assert f'href="{reverse("shop_dispatchers:index")}"' in page


def test_see_dispatchers_sent_and_empty(client, shop_variants, dispatcher):
    shop_admin(client)
    page = content(client.get(URL, {"dispatcher": dispatcher.pk}))
    assert "Ann Smith has nothing to send at the moment." in page
    page = content(client.get(URL, {"dispatcher": dispatcher.pk, "sent": ""}))
    assert "Ann Smith hasn't sent anything yet." in page


def test_see_dispatchers_orders_cant_mark_shipped(client, shop_variants, dispatcher):
    mug, card, raffle = shop_variants
    order = order_with([mug])
    shop_admin(client)
    resp = client.post(f"{URL}?dispatcher={dispatcher.pk}", {"order": order.pk})
    assert resp.url == reverse("wagtailadmin_home")
    assert order.items.get().shipping_status == OrderItem.TO_SEND


def test_see_dispatchers_orders_permission(client, dispatcher):
    # e.g. another dispatcher, or an orders-only user
    other = make_dispatcher("Bob", "bob@test.com")
    client.force_login(other)
    assert client.get(URL, {"dispatcher": dispatcher.pk}).url == reverse("wagtailadmin_home")


def test_see_non_dispatcher(client):
    # only dispatchers' pages
    shop_admin(client)
    user = baker.make("auth.User")
    assert client.get(URL, {"dispatcher": user.pk}).status_code == 404


def test_dispatchers_page_links(client, dispatcher):
    shop_admin(client)
    page = client.get(reverse("shop_dispatchers:index")).content.decode()
    assert f'href="{URL}?dispatcher={dispatcher.pk}"' in page
    assert "See their items to send" in page
