"""Browsing the shop, and the basket"""

import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect

from ...models import ProductVariant, Sale, SaleProduct
from .conftest import E2E, PHONE, add_to_basket, card, choose_option

pytestmark = E2E


def test_browse_and_add(page, live_server, shop):
    page.goto(f"{live_server.url}/shop/")
    # grouped by category, with prices and stock notes
    expect(page.get_by_role("heading", name="Clothing")).to_be_visible()
    tshirt = card(page, "PINS T-shirt")
    expect(tshirt).to_contain_text("£18.00")
    expect(tshirt.locator("select[name=variant_id]")).to_contain_text("Black, S (only 2 left)")
    # the out-of-stock option can't be chosen
    expect(tshirt.locator("option", has_text="Black, M")).to_be_disabled()
    # a category's button shows just its products
    page.get_by_role("link", name="Cards", exact=True).click()
    expect(page).to_have_url(re.compile(r"\?category=cards$"))
    page.wait_for_load_state()
    expect(page.locator("article.shop-card")).to_have_count(1)
    # adding: "Added!", the basket count, and what's in the basket
    page.get_by_role("link", name="All", exact=True).click()
    # (once htmx has loaded)
    page.wait_for_load_state()
    mug = card(page, "Podenco mug")
    mug.get_by_role("button", name="Add to basket").click()
    expect(mug.get_by_text("Added!")).to_be_visible()
    expect(page.locator("#basket-icon")).to_contain_text("1")
    expect(mug.locator(".shop-in-basket")).to_have_text("1 in your basket")


def test_quantity_limits(page, live_server, shop):
    # Black, S has 2 left: "+" stops at 2
    page.goto(f"{live_server.url}{reverse('shop:product_detail', args=(shop['tshirt'].pk,))}")
    form = page.locator(".shop-product")
    more, fewer = form.get_by_role("button", name="More"), form.get_by_role("button", name="Fewer")
    expect(fewer).to_be_disabled()
    more.click()
    expect(form.locator("input.quantity")).to_have_value("2")
    expect(more).to_be_disabled()
    # another option: its own limit (5), and the quantity is kept
    choose_option(form, "White, M")
    expect(more).to_be_enabled()


def test_adding_the_last_ones(page, live_server, shop):
    # once out of stock, what's in the basket is still shown, and after reloading
    shop["mug"].variants.update(stock=1)
    shop["tshirt"].variants.update(stock=0)
    shop["tshirt"].variants.filter(size="S").update(stock=1)
    page.goto(f"{live_server.url}/shop/")
    page.wait_for_load_state()
    for name, text in [("Podenco mug", "1 in your basket"), ("PINS T-shirt", "In your basket: Black, S × 1")]:
        product = card(page, name)
        product.get_by_role("button", name="Add to basket").click()
        expect(product.get_by_text("Added!")).to_be_visible()
        expect(product.get_by_text("Out of stock")).to_be_visible()
        expect(product.locator(".shop-form .shop-in-basket")).to_have_text(text)
    page.reload()
    expect(card(page, "Podenco mug").locator(".shop-form .shop-in-basket")).to_have_text("1 in your basket")
    expect(card(page, "PINS T-shirt").locator(".shop-form .shop-in-basket")).to_have_text("In your basket: Black, S × 1")


def test_stock_taken_meanwhile(page, live_server, shop):
    # the page shows 2 left; someone else buys them before "+" is pressed
    page.goto(f"{live_server.url}{reverse('shop:product_detail', args=(shop['tshirt'].pk,))}")
    ProductVariant.objects.filter(product=shop["tshirt"], size="S").update(stock=0)
    form = page.locator(".shop-product")
    form.get_by_role("button", name="Add to basket").click()
    expect(form.get_by_text("None available")).to_be_visible()
    expect(form.locator("option", has_text="Black, S")).to_contain_text("out of stock")


def test_basket(page, live_server, shop):
    add_to_basket(page, live_server, shop["mug"], quantity=2)
    add_to_basket(page, live_server, shop["tshirt"], option="White, M")
    page.goto(f"{live_server.url}/shop/basket/")
    # 2 x £10 + £18, with £4.99 delivery
    total = page.locator("#total")
    expect(total).to_have_text("42.99")
    # quantities and removing items update the totals (htmx)
    mug = page.locator(".basket-item", has_text="Podenco mug")
    mug.get_by_role("button", name="Fewer").click()
    expect(total).to_have_text("32.99")
    page.locator(".basket-item", has_text="PINS T-shirt").get_by_role("button", name=re.compile("Remove")).click()
    expect(page.locator(".basket-item")).to_have_count(1)
    expect(total).to_have_text("14.99")
    # collection: no shipping cost, and the choice is kept on reloading
    page.get_by_label("Collect in person (prior arrangement only)").check()
    expect(total).to_have_text("10.00")
    page.reload()
    expect(page.get_by_label("Collect in person (prior arrangement only)")).to_be_checked()
    # removing the last item: the empty basket
    page.locator(".basket-item").get_by_role("button", name=re.compile("Remove")).click()
    expect(page.get_by_text("Your basket is empty.")).to_be_visible()


def test_basket_quick_clicks(page, live_server, shop):
    # pressing + quickly: the item's requests run in turn, one update for each
    # change, and the basket ends up right
    add_to_basket(page, live_server, shop["mug"])
    add_to_basket(page, live_server, shop["raffle"])
    page.goto(f"{live_server.url}/shop/basket/")
    page.wait_for_load_state()
    updates = []
    page.on("request", lambda request: "/update/" in request.url and updates.append(request.url))
    mug = page.locator(".basket-item", has_text="Podenco mug")
    for _ in range(3):
        mug.get_by_role("button", name="More").click()
    # 4 x £10 + £2, with £4.99 delivery
    expect(page.locator("#total")).to_have_text("46.99")
    assert len(updates) == 3
    page.locator(".basket-item", has_text="Raffle ticket").get_by_role("button", name=re.compile("Remove")).click()
    expect(page.locator(".basket-item")).to_have_count(1)
    page.reload()
    expect(mug.get_by_label("Quantity")).to_have_value("4")
    expect(page.locator("#total")).to_have_text("44.99")


def test_basket_typed_quantity(page, live_server, shop):
    add_to_basket(page, live_server, shop["mug"])
    page.goto(f"{live_server.url}/shop/basket/")
    page.wait_for_load_state()
    total = page.locator("#total")
    quantity = page.locator(".basket-item").get_by_label("Quantity")
    # Enter updates the item to the typed quantity (and doesn't remove it)
    quantity.fill("3")
    quantity.press("Enter")
    expect(total).to_have_text("34.99")
    expect(page.get_by_text("Basket updated")).to_be_visible()
    page.reload()
    expect(quantity).to_have_value("3")
    # as does leaving the field
    quantity.fill("2")
    quantity.press("Tab")
    expect(total).to_have_text("24.99")
    # more than there is: the most there is (5)
    quantity.fill("9")
    expect(quantity).to_have_value("5")
    quantity.press("Enter")
    expect(total).to_have_text("54.99")
    # not a quantity: back to the item's
    quantity.fill("0")
    quantity.press("Enter")
    expect(quantity).to_have_value("5")
    expect(page.locator(".basket-item")).to_have_count(1)


# (a short window, so the basket page scrolls)
@pytest.mark.parametrize(
    "browser_context_args", [{"viewport": {"width": 1280, "height": 500}}], indirect=True
)
def test_discount_codes(page, live_server, shop):
    add_to_basket(page, live_server, shop["mug"])
    page.goto(f"{live_server.url}/shop/basket/")
    # scrolled part of the way down (not to the bottom, where a change in the
    # page's height would move it), with the discount code field in view
    page.evaluate("window.scrollTo(0, 150)")
    page.evaluate("window.notReloaded = true")
    scroll = page.evaluate("scrollY")
    assert scroll == 150
    code = page.get_by_label("Discount code")
    code.fill("nope")
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_text("Invalid discount code.")).to_be_visible()
    page.get_by_label("Discount code").fill("test5")
    page.get_by_role("button", name="Apply").click()
    expect(page.get_by_text("Discount code TEST5 applied.")).to_be_visible()
    # £10 + £4.99, less £5; the page didn't reload or scroll
    expect(page.locator("#total")).to_have_text("9.99")
    assert page.evaluate("window.notReloaded") is True
    assert page.evaluate("scrollY") == scroll
    page.locator("#basket-extra").get_by_role("button", name="Remove").click()
    expect(page.get_by_text("Discount code removed.")).to_be_visible()
    expect(page.locator("#total")).to_have_text("14.99")


def test_packs(page, live_server, shop):
    # 12 cards: 2 packs of 5 (and the singles) can be added
    add_to_basket(page, live_server, shop["cards"], quantity=2, option="Pack of 5")
    form = page.locator(".shop-product")
    expect(form.locator("option", has_text="Pack of 5")).to_contain_text("out of stock")
    expect(form.locator("option", has_text="Single")).to_contain_text("only 2 left")
    shop["cards"].refresh_from_db()
    assert shop["cards"].stock == 2


@pytest.mark.parametrize("browser_context_args", [PHONE], indirect=True)
def test_phone(page, live_server, shop):
    page.goto(f"{live_server.url}/shop/")
    # products with options: "Choose options", which goes to their page
    tshirt = card(page, "PINS T-shirt")
    expect(tshirt.get_by_role("button", name="Add to basket")).to_be_hidden()
    tshirt.get_by_role("link", name="Choose options").click()
    expect(page.get_by_role("heading", name="PINS T-shirt", level=1)).to_be_visible()
    page.wait_for_load_state()
    page.locator(".shop-product").get_by_role("button", name="Add to basket").click()
    expect(page.locator(".shop-product").get_by_text("Added!")).to_be_visible()
    # back on the shop page: the button is still pink, not Bootstrap's grey
    page.go_back()
    choose = card(page, "PINS T-shirt").get_by_role("link", name="Choose options")
    expect(choose).to_have_css("background-color", "rgb(163, 90, 71)")
    expect(card(page, "PINS T-shirt").locator(".shop-in-basket--compact")).to_have_text("1 in your basket")


def test_sale(page, live_server, shop):
    # the banner's white text on the sale's red, and the price before the sale
    # in red
    now = timezone.now()
    sale = Sale.objects.create(
        name="Sale", banner_title="Sale now on!", banner_content="Discounts across the shop.", banner_include_end=True,
        start_date=now - timedelta(days=1), end_date=now + timedelta(days=1),
    )
    SaleProduct.objects.create(sale=sale, product=shop["mug"], discount=20)
    page.goto(f"{live_server.url}/shop/")
    banner = page.locator(".shop-sale-banner")
    expect(banner).to_have_css("background-color", "rgb(179, 38, 30)")
    for text in ["Sale now on!", "Discounts across the shop.", "Sale ends on"]:
        expect(banner.get_by_text(text)).to_have_css("color", "rgb(255, 255, 255)")
    expect(card(page, "Podenco mug").locator(".shop-card__price s")).to_have_css("color", "rgb(179, 38, 30)")
