"""The header's Login link and Account menu, the menu's drop-downs, and messages"""

import re

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from model_bakery import baker
from playwright.sync_api import expect

from shop.tests.e2e.conftest import log_in

from .conftest import E2E

pytestmark = E2E

PINS_STRONG = "rgb(163, 90, 71)"


def desktop_menu(page):
    return page.get_by_role("navigation", name="Main")


def test_login_hidden(page, live_server, site_pages, settings):
    # only auctions need logging in, so no Login link (unless SHOW_LOGIN, which
    # is off by default)
    settings.SHOW_LOGIN = False
    page.goto(live_server.url)
    expect(desktop_menu(page).get_by_role("link", name="Login")).to_have_count(0)
    expect(desktop_menu(page).get_by_role("button", name="Account")).to_have_count(0)


def test_login_shown(page, live_server, site_pages, settings):
    settings.SHOW_LOGIN = True
    page.goto(live_server.url)
    login = desktop_menu(page).get_by_role("link", name="Login")
    # in PINS's colour, like Account
    expect(login).to_have_css("color", PINS_STRONG)
    login.click()
    expect(page).to_have_url(re.compile(re.escape(reverse("account_login")) + r"\?next=/"))


def test_login_page_menu_aligned(page, live_server, site_pages):
    # the account pages' button style doesn't push down the menu's drop-downs
    page.goto(live_server.url + reverse("account_login"))
    # (the page with child pages, beside its drop-down's button, in line with the others)
    menu = desktop_menu(page)
    dogs = menu.get_by_role("link", name="Dogs", exact=True).bounding_box()
    about = menu.get_by_role("link", name="About us").bounding_box()
    assert abs(dogs["y"] - about["y"]) < 3


@pytest.mark.parametrize(
    "groups,label",
    [
        (["Shop admins"], "Shop admin"),
        (["Shop manager"], "Shop admin"),
        (["Dispatchers"], "Shop admin"),
        (["Shop manager", "Dispatchers"], "Shop admin"),
        ([], None),
        ("superuser", "Admin"),
    ],
)
def test_account_menu(page, live_server, site_pages, groups, label):
    # the admin, for users who can use it ("Shop admin" for shop staff only), and Logout
    if groups == "superuser":
        user = baker.make("auth.User", is_superuser=True)
    else:
        user = baker.make("auth.User")
        user.groups.add(*Group.objects.filter(name__in=groups))
    log_in(page, live_server, user)
    page.goto(live_server.url)
    account = desktop_menu(page).get_by_role("button", name="Account")
    expect(account).to_have_css("color", PINS_STRONG)
    account.click()
    if label:
        menu_link = desktop_menu(page).get_by_role("link", name=label, exact=True)
        expect(menu_link).to_have_attribute("href", reverse("wagtailadmin_home"))
    else:
        expect(desktop_menu(page).get_by_role("link", name=re.compile("Admin"))).to_have_count(0)
    # (logging out goes back to the home page)
    desktop_menu(page).get_by_role("link", name="Logout").click()
    expect(desktop_menu(page).get_by_role("button", name="Account")).to_have_count(0)


@pytest.mark.parametrize("groups,label", [(["Shop manager", "Editors"], "Admin"), (["Shop manager"], "Shop admin")])
def test_account_menu_other_admins(page, live_server, site_pages, groups, label):
    # in another group too, e.g. page editors: "Admin"; but only the shop's
    # groups, whatever the user's own permissions: "Shop admin"
    user = baker.make("auth.User")
    user.user_permissions.add(Permission.objects.get(codename="access_admin"))
    user.groups.add(*Group.objects.filter(name__in=groups))
    log_in(page, live_server, user)
    page.goto(live_server.url)
    desktop_menu(page).get_by_role("button", name="Account").click()
    expect(desktop_menu(page).get_by_role("link", name=label, exact=True)).to_be_visible()


def test_messages(page, live_server, site_pages):
    # e.g. after logging out: a card on the cream, with a bar in PINS's
    # colour, and dark text
    log_in(page, live_server, baker.make("auth.User"))
    page.goto(live_server.url + reverse("account_logout"))
    message = page.locator(".site-message")
    expect(message).to_contain_text("signed out")
    expect(message).to_have_css("background-color", "rgb(245, 243, 233)")
    expect(message).to_have_css("border-left-color", PINS_STRONG)
    expect(message).to_have_css("color", "rgb(51, 51, 51)")


@pytest.mark.parametrize("url", ["/", "basket"])
def test_footer_at_bottom(page, live_server, site_pages, url):
    # on short pages (e.g. an empty basket), the footer is at the bottom of
    # the window, not straight after the content
    url = reverse("shop:basket") if url == "basket" else url
    page.goto(live_server.url + url)
    footer = page.locator("footer").bounding_box()
    height = page.evaluate("innerHeight")
    assert page.evaluate("document.documentElement.scrollHeight") == height
    assert abs(footer["y"] + footer["height"] - height) < 2


def test_footer_after_long_content(page, live_server, site_pages):
    # (on long pages, after the content as before)
    page.set_viewport_size({"width": 1280, "height": 400})
    page.goto(live_server.url + site_pages["dog"].get_url_parts()[2])
    main = page.locator("main").bounding_box()
    footer = page.locator("footer").bounding_box()
    assert footer["y"] > main["y"] + main["height"]
    assert page.evaluate("document.documentElement.scrollHeight") > 400
