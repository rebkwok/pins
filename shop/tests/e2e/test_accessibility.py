"""
Accessibility: axe-core on the main shop and admin pages, failing on serious
or critical issues
"""

from pprint import pformat

import pytest
from axe_playwright_python.sync_playwright import Axe
from django.urls import reverse
from playwright.sync_api import expect

from .conftest import E2E, PHONE, add_to_basket, log_in
from .test_admin import paid_order  # noqa: F401 (a fixture)

pytestmark = E2E

SERIOUS = {"serious", "critical"}

# Known issues that aren't the shop's: (rule, element)
KNOWN = {
    # the site's header navigation (its list's markup): step 17
    ("list", ".navigation__desktop > ul:nth-child(2)"),
    # Wagtail's rich text editor (Draftail), in the admin
    ("aria-input-field-name", ".notranslate"),
}


def serious_issues(page):
    """
    axe's serious and critical issues on the page (apart from KNOWN ones):
    [(rule, impact, [elements])]
    """
    issues = []
    for violation in Axe().run(page).response["violations"]:
        if violation["impact"] not in SERIOUS:
            continue
        targets = [
            " ".join(node["target"])
            for node in violation["nodes"]
            if (violation["id"], " ".join(node["target"])) not in KNOWN
        ]
        if targets:
            issues.append((violation["id"], violation["impact"], targets[:5]))
    return issues


def shop_pages(live_server, shop, order):
    return {
        "shop": "/shop/",
        "category": "/shop/?category=clothing",
        "product": reverse("shop:product_detail", args=(shop["tshirt"].pk,)),
        "basket": reverse("shop:basket"),
        "checkout": reverse("shop:checkout") + "?payment-method=stripe&shipping-method=deliver",
        "order status": reverse("shop:order_status", args=(order.token,)),
        "faqs": reverse("shop:faqs"),
    }


@pytest.mark.parametrize("browser_context_args", [None, PHONE], indirect=True, ids=["desktop", "phone"])
def test_shop_pages(page, live_server, shop, paid_order):
    add_to_basket(page, live_server, shop["mug"])
    issues = {}
    for name, url in shop_pages(live_server, shop, paid_order).items():
        page.goto(live_server.url + url)
        page.wait_for_load_state()
        found = serious_issues(page)
        if found:
            issues[name] = found
    assert issues == {}, pformat(issues, width=120)


def test_admin_pages(page, live_server, admin_user, shop, paid_order):
    log_in(page, live_server, admin_user)
    issues = {}
    for name, url in {
        "orders": reverse("shop_orders:index"),
        "order": reverse("shop_orders:edit", args=(paid_order.pk,)),
        "dispatcher activity": reverse("shop_dispatchers:index"),
        "shop activity": reverse("shop_activity:index"),
        "product": reverse("wagtailsnippets_shop_product:edit", args=(shop["mug"].pk,)),
        "shipping rates": reverse("wagtailsnippets_shop_shippingrate:list"),
    }.items():
        page.goto(live_server.url + url)
        expect(page.locator("main")).to_be_visible()
        found = serious_issues(page)
        if found:
            issues[name] = found
    assert issues == {}, pformat(issues, width=120)
