"""
Accessibility: axe-core on one page of each type, and the site's other pages,
failing on any issue (the shop's pages are in shop/tests/e2e)
"""

from pprint import pformat

import pytest
from axe_playwright_python.sync_playwright import Axe
from django.urls import reverse
from model_bakery import baker

from shop.tests.e2e.conftest import log_in

from .conftest import E2E, PHONE

pytestmark = E2E


def issues(page):
    """axe's issues on the page: [(rule, impact, [elements])]"""
    return [
        (violation["id"], violation["impact"], [" ".join(node["target"]) for node in violation["nodes"]][:5])
        for violation in Axe().run(page).response["violations"]
    ]


def check(page, live_server, urls):
    found = {}
    for name, url in urls.items():
        page.goto(live_server.url + url)
        page.wait_for_load_state()
        page_issues = issues(page)
        if page_issues:
            found[name] = page_issues
    assert found == {}, pformat(found, width=120)


def page_urls(site_pages):
    # (the pages' paths: their urls include the test site's hostname)
    return {name: page.get_url_parts()[2] for name, page in site_pages.items()}


@pytest.mark.parametrize("browser_context_args", [None, PHONE], indirect=True, ids=["desktop", "phone"])
def test_pages(page, live_server, site_pages):
    check(
        page,
        live_server,
        {
            **page_urls(site_pages),
            "search": reverse("search") + "?query=rex",
            "login": reverse("account_login"),
            "signup": reverse("account_signup"),
            "password reset": reverse("account_reset_password"),
            "recipe contribution": reverse("fundraising:recipe_book_contribution_add"),
            "merchandise information": reverse("merch_info"),
        },
    )


def test_pages_logged_in(page, live_server, site_pages):
    log_in(page, live_server, baker.make("auth.User", first_name="Ann", email="ann@test.com"))
    check(
        page,
        live_server,
        {
            "home": "/",
            "auction": page_urls(site_pages)["auction"],
            "your bids": reverse("fundraising:user_bids", args=(site_pages["auction"].slug,)),
            "recipe contribution": reverse("fundraising:recipe_book_contribution_add"),
        },
    )
