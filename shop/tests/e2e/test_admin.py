"""The shop's admin: orders, products' stock, dispatchers, and roles"""

import io
import re

import pytest
from django.core import mail
from django.urls import reverse
from model_bakery import baker
from openpyxl import load_workbook
from playwright.sync_api import expect
from salesman.core.utils import get_salesman_model

from ...models import OrderItem
from .conftest import E2E, PHONE, log_in, user_in

pytestmark = E2E

Order = get_salesman_model("Order")


@pytest.fixture
def paid_order(shop):
    """Cat's paid order for 2 mugs (sent by Ann) and a T-shirt (no dispatcher), delivered"""
    basket = baker.make(
        "shop.Basket",
        shipping_method="deliver",
        extra={"email": "cat@test.com", "name": "Cat Customer", "phone": "07700 900123", "safe_place": "Porch"},
    )
    basket.add(shop["mug"].variants.get(), quantity=2)
    basket.add(shop["tshirt"].variants.get(size="S"))
    basket.update(request=None)
    order = Order.objects.create_from_basket(basket, None, status=Order.Status.PROCESSING)
    order.shipping_address = "1 Road\nTown\nSW1A 1AA\nUnited Kingdom"
    order.save()
    order.pay(amount=order.total, transaction_id="pi_1", payment_method="stripe")
    mail.outbox.clear()
    return order


def order_url(live_server, order):
    return live_server.url + reverse("shop_orders:edit", args=(order.pk,))


def test_order_page(page, live_server, admin_user, paid_order):
    log_in(page, live_server, admin_user)
    page.goto(order_url(live_server, paid_order))
    expect(page.get_by_text("Paid – ready to ship")).to_be_visible()
    expect(page.get_by_role("link", name="07700 900123")).to_be_visible()
    expect(page.get_by_role("button", name="Mark as completed")).to_be_disabled()
    # mark the mugs shipped: the customer is emailed, and it's logged
    page.get_by_label(re.compile("Select .*Podenco mug")).check()
    page.get_by_role("button", name="Mark selected items as shipped").click()
    # (confirming first: nothing's been emailed yet)
    expect(page.get_by_role("heading", name="Mark these items as shipped?")).to_be_visible()
    assert not mail.outbox
    page.get_by_role("button", name="Yes, mark as shipped").click()
    expect(page.get_by_text("1 item marked shipped, and the customer has been emailed.")).to_be_visible()
    expect(page.get_by_text("Partly shipped")).to_be_visible()
    assert [message.to for message in mail.outbox] == [["cat@test.com"]]
    activity = page.locator("table.shop-order__activity")
    expect(activity).to_contain_text("Marked shipped: 2 × Podenco mug")
    expect(activity).to_contain_text("Ada")
    # undoing it (by mistake, say), then shipping them again
    page.get_by_role("button", name="Undo marking Podenco mug as shipped").click()
    page.get_by_role("button", name="Yes, undo").click()
    expect(page.get_by_text("Undone: 1 item is ready to send again. The customer hasn't been emailed.")).to_be_visible()
    expect(page.get_by_text("Paid – ready to ship")).to_be_visible()
    expect(activity).to_contain_text("Undone, ready to send again: 2 × Podenco mug")
    # the back button: to the page to confirm, which has nothing left to do, so
    # back to the order
    page.go_back()
    expect(page.get_by_text("Those items have already been changed.")).to_be_visible()
    expect(page).to_have_url(order_url(live_server, paid_order))
    page.get_by_label(re.compile("Select .*Podenco mug")).check()
    page.get_by_role("button", name="Mark selected items as shipped").click()
    page.get_by_role("button", name="Yes, mark as shipped").click()
    expect(page.get_by_text("Partly shipped")).to_be_visible()
    # the T-shirt won't be sent; then the order can be completed
    page.get_by_label(re.compile("Select .*PINS T-shirt")).check()
    page.get_by_role("button", name="Mark selected items as won't be sent").click()
    page.get_by_role("button", name="Yes, mark as won't be sent").click()
    page.get_by_role("link", name="Mark as completed").click()
    page.get_by_role("button", name="Mark as completed").click()
    expect(page.get_by_text(f"Order {paid_order.ref} is completed")).to_be_visible()
    # a note
    page.get_by_label("Note").fill("Customer called about the T-shirt")
    page.get_by_role("button", name="Add note").click()
    expect(page.locator("table.shop-order__activity")).to_contain_text(
        "Added a note: Customer called about the T-shirt"
    )
    # the customer's order page (a new tab)
    with page.context.expect_page() as new_tab:
        page.get_by_role("link", name="Customer's order page").click()
    expect(new_tab.value.get_by_text(f"Order {paid_order.ref}")).to_be_visible()


def test_orders_download(page, live_server, admin_user, paid_order):
    log_in(page, live_server, admin_user)
    page.goto(live_server.url + reverse("shop_orders:index"))
    # (its label says how many orders are ticked)
    download_button = page.get_by_role("button", name=re.compile(r"^Download.*\(Excel\)$"))
    expect(download_button).to_be_disabled()
    page.get_by_label(f"Select order {paid_order.ref}, to download").check()
    expect(download_button).to_have_text("Download 1 order (Excel)")
    with page.expect_download() as download:
        download_button.click()
    assert re.fullmatch(r"orders-\d{4}-\d{2}-\d{2}-\d{4}\.xlsx", download.value.suggested_filename)
    with open(download.value.path(), "rb") as file:
        rows = list(load_workbook(io.BytesIO(file.read())).active.values)
    assert "Mobile number" in rows[0] and "Safe place" in rows[0]
    assert {row[0] for row in rows[1:]} == {paid_order.ref}


def test_product_stock_fields(page, live_server, admin_user, shop):
    # only the stock fields that apply, as the boxes are ticked
    log_in(page, live_server, admin_user)
    page.goto(live_server.url + reverse("wagtailsnippets_shop_product:edit", args=(shop["mug"].pk,)))
    variant_stock = page.locator("[name='variants-0-stock']")
    expect(variant_stock).to_be_visible()
    page.get_by_label("No stock limit").check()
    expect(variant_stock).to_be_hidden()
    expect(page.get_by_label("Variants share stock")).to_be_disabled()
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text("Product 'Podenco mug' updated.")).to_be_visible()
    shop["mug"].refresh_from_db()
    assert shop["mug"].unlimited_stock
    # what changed is logged
    page.goto(live_server.url + reverse("shop_activity:index"))
    expect(page.get_by_text("Edited: No stock limit: no → yes")).to_be_visible()


def test_shop_admin(page, live_server, paid_order):
    log_in(page, live_server, user_in("Shop admins", username="sam"))
    page.goto(live_server.url + reverse("wagtailadmin_home"))
    menu = page.locator("#wagtail-sidebar")
    for item in ["Orders", "Dispatcher activity", "Shop stock", "Shop admin"]:
        # (submenus' names are also their headings)
        expect(menu.get_by_text(item, exact=True).first).to_be_visible()
    # (not Images: they add images from products' pages)
    expect(menu.get_by_text("Images", exact=True)).to_have_count(0)
    # Dispatcher activity: Ann has 1 item pending; the T-shirt has no dispatcher
    page.goto(live_server.url + reverse("shop_dispatchers:index"))
    expect(page.get_by_role("link", name="Pending items (1)")).to_have_count(2)


def test_shop_manager_starts_at_orders(page, live_server, paid_order):
    log_in(page, live_server, user_in("Shop manager"))
    page.goto(live_server.url + reverse("wagtailadmin_home"))
    expect(page).to_have_url(re.compile(re.escape(reverse("shop_orders:index")) + "$"))


@pytest.mark.parametrize("browser_context_args", [PHONE], indirect=True)
def test_dispatcher_on_phone(page, live_server, paid_order, dispatcher):
    # Ann sends her mugs, on her phone
    log_in(page, live_server, dispatcher)
    page.goto(live_server.url + reverse("wagtailadmin_home"))
    expect(page).to_have_url(re.compile(re.escape(reverse("shop_dispatch:index")) + "$"))
    order = page.locator(".dispatch-order", has_text=paid_order.ref)
    expect(order).to_contain_text("Porch")
    order.get_by_role("button", name=re.compile("Mark .*shipped")).click()
    page.get_by_role("button", name="Yes, mark as shipped").click()
    expect(page.get_by_text(re.compile("marked shipped"))).to_be_visible()
    assert paid_order.items.filter(dispatcher=dispatcher, shipping_status=OrderItem.SHIPPED).count() == 1


@pytest.mark.parametrize("browser_context_args", [PHONE], indirect=True)
def test_order_page_buttons_on_phone(page, live_server, admin_user, paid_order):
    # the item buttons, wrapped onto two lines, line up
    log_in(page, live_server, admin_user)
    page.goto(order_url(live_server, paid_order))
    ship = page.get_by_role("button", name="Mark selected items as shipped").bounding_box()
    not_sent = page.get_by_role("button", name="Mark selected items as won't be sent").bounding_box()
    assert not_sent["y"] > ship["y"]
    assert not_sent["x"] == ship["x"]


@pytest.mark.parametrize("browser_context_args", [PHONE], indirect=True)
def test_orders_list_on_phone(page, live_server, admin_user, paid_order):
    # wider than the screen (a long email, the items open): the list scrolls
    # sideways, not the page (Wagtail's main area would cut it off)
    paid_order.email = "catherine.customer.with.a.long.address@example.com"
    paid_order.save()
    log_in(page, live_server, admin_user)
    page.goto(live_server.url + reverse("shop_orders:index"))
    page.get_by_text("2 items").click()
    scroll = page.locator(".shop-orders-scroll")
    width = page.evaluate("innerWidth")
    assert page.evaluate("document.documentElement.scrollWidth") == width
    assert scroll.evaluate("e => e.scrollWidth > e.clientWidth")
    status = page.locator("table.listing td", has_text="Paid – ready to ship")
    status.scroll_into_view_if_needed()
    expect(status).to_be_in_viewport()
