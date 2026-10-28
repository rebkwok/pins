"""Checking out: paying (Stripe faked), free orders, cancelling, and expiry"""

import re
from django.core import mail
from playwright.sync_api import expect
from salesman.core.utils import get_salesman_model

from ...models import ProductVariant
from .conftest import E2E, add_to_basket, field, fill_checkout

pytestmark = E2E

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")


def go_to_checkout(page, live_server):
    page.goto(f"{live_server.url}/shop/basket/")
    page.get_by_role("button", name="Checkout").click()
    expect(page.get_by_role("heading", name="Checkout", level=1)).to_be_visible()


def test_delivery_order(page, live_server, shop, stripe):
    add_to_basket(page, live_server, shop["mug"], quantity=2)
    go_to_checkout(page, live_server)
    expect(page.get_by_text("Clicking Pay Now takes you to Stripe")).to_be_visible()
    # consent is required (the browser won't submit without it)
    fill_checkout(page)
    page.get_by_label(re.compile("Data Privacy Policy")).uncheck()
    page.get_by_role("button", name="Pay Now").click()
    expect(page.get_by_role("heading", name="Checkout", level=1)).to_be_visible()
    assert not Order.objects.exists()
    # paying (on Stripe's page, faked): back to "Order confirmed"
    page.get_by_label(re.compile("Data Privacy Policy")).check()
    page.get_by_role("button", name="Pay Now").click()
    expect(page.get_by_role("heading", name="Order confirmed")).to_be_visible()
    order = Order.objects.get()
    expect(page.get_by_text(f"Your order reference is {order.ref}.")).to_be_visible()
    assert order.status == Order.Status.PROCESSING
    assert (order.name, order.phone, order.safe_place) == ("Cat Customer", "07700 900123", "Porch")
    assert order.shipping_address == "1 Road\nTown\nSW1A 1AA\nUnited Kingdom"
    assert order.consent_at is not None
    # stock taken; the basket emptied
    assert ProductVariant.objects.get(product=shop["mug"]).stock == 3
    assert not Basket.objects.exists()
    # the customer, the dispatcher (Ann), and (if set) the shop are emailed
    recipients = [message.to for message in mail.outbox]
    assert ["cat@test.com"] in recipients
    assert ["ann@test.com"] in recipients
    # the order status page
    page.get_by_role("link", name="View your order").click()
    expect(page.get_by_text(f"Order {order.ref}")).to_be_visible()
    expect(page.get_by_text("To be sent")).to_be_visible()
    expect(page.get_by_text("Porch")).to_be_visible()


def test_collection_and_other_country(page, live_server, shop, stripe):
    add_to_basket(page, live_server, shop["mug"])
    page.goto(f"{live_server.url}/shop/basket/")
    page.get_by_label("Collect in person (prior arrangement only)").check()
    expect(page.locator("#total")).to_have_text("10.00")
    page.get_by_role("button", name="Checkout").click()
    # no address for collection
    expect(field(page, "Address line 1")).to_have_count(0)
    expect(page.get_by_text("Optional: to arrange collection.")).to_be_visible()
    # back to delivery, outside the UK
    page.get_by_role("link", name=re.compile("Back to basket")).click()
    page.get_by_label("Delivery", exact=True).check()
    page.get_by_role("button", name="Checkout").click()
    which = field(page, "Which country?")
    expect(which).to_be_hidden()
    field(page, "Country").select_option("other")
    expect(which).to_be_visible()
    fill_checkout(page, **{"Postcode": "75001", "Which country?": "France"})
    page.get_by_role("button", name="Pay Now").click()
    expect(page.get_by_role("heading", name="Order confirmed")).to_be_visible()
    order = Order.objects.get()
    assert order.outside_uk
    assert "OUTSIDE THE UK" in next(m.body for m in mail.outbox if m.to == ["ann@test.com"])


def test_no_shipping_needed(page, live_server, shop, stripe):
    # a raffle ticket: no delivery options or address
    add_to_basket(page, live_server, shop["raffle"], quantity=3)
    page.goto(f"{live_server.url}/shop/basket/")
    expect(page.get_by_text("Nothing in your basket needs shipping.")).to_be_visible()
    expect(page.locator("#total")).to_have_text("6.00")
    page.get_by_role("button", name="Checkout").click()
    expect(page.get_by_text("Delivery address")).to_have_count(0)
    fill_checkout(page, delivery=False)
    page.get_by_role("button", name="Pay Now").click()
    expect(page.get_by_role("heading", name="Order confirmed")).to_be_visible()
    order = Order.objects.get()
    # nothing to send: complete
    assert order.status == Order.Status.COMPLETED


def test_free_order(page, live_server, shop, stripe, requests_mock):
    add_to_basket(page, live_server, shop["mug"])
    page.goto(f"{live_server.url}/shop/basket/")
    page.get_by_label("Discount code").fill("FREE100")
    page.get_by_role("button", name="Apply").click()
    expect(page.locator("#total")).to_have_text("0.00")
    page.get_by_role("button", name="Checkout").click()
    # nothing to pay: no Stripe
    expect(page.get_by_text("Clicking Pay Now takes you to Stripe")).to_have_count(0)
    fill_checkout(page)
    page.get_by_role("button", name="Place order").click()
    expect(page.get_by_text("Thank you for your order!")).to_be_visible()
    assert Order.objects.get().discount_code == "FREE100"
    assert not requests_mock.called


def test_cancelled_payment(page, live_server, shop, stripe):
    stripe["cancel"] = True
    add_to_basket(page, live_server, shop["mug"])
    go_to_checkout(page, live_server)
    fill_checkout(page)
    page.get_by_role("button", name="Pay Now").click()
    # Stripe's page (faked) sends them back to "Payment cancelled"
    expect(page.get_by_role("heading", name="Payment cancelled")).to_be_visible()
    page.get_by_role("link", name="Return to your basket").click()
    # (cancelling ended the payment) the basket, with its items, can be changed
    expect(page.locator(".basket-item", has_text="Podenco mug")).to_be_visible()
    expect(page.get_by_text("Payment in progress")).to_have_count(0)
    expect(page.locator(".basket-item").get_by_role("button", name="More")).to_be_enabled()
    assert not Order.objects.exists()


def test_basket_expires(page, live_server, shop, settings):
    # (a few seconds, for the test; the live server runs in this process)
    settings.BASKET_TIMEOUT_MINUTES = 0.1
    add_to_basket(page, live_server, shop["mug"])
    page.goto(f"{live_server.url}/shop/basket/")
    expect(page.locator("#countdown")).to_have_text(re.compile(r"0m [0-6]s"))
    # when it reaches 0, the page is reloaded, with the basket emptied
    expect(page.get_by_text("Your basket has expired.")).to_be_visible(timeout=15_000)
    expect(page.get_by_text("Your basket is empty.")).to_be_visible()
    assert ProductVariant.objects.get(product=shop["mug"]).stock == 5
