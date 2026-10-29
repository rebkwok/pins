"""
SHOP_PREVIEW: while the shop is a hidden preview, its pages aren't listed by
search engines; SHOP_TEST_MODE: a banner says it's in test mode
"""

import pytest
from django.urls import reverse

from .test_shop_page import shop  # noqa: F401

pytestmark = pytest.mark.django_db

NOINDEX = '<meta name="robots" content="noindex, nofollow">'


def shop_urls(shop):
    page, products = shop
    return [
        page.url,
        reverse("shop:product_detail", args=(products["Podenco mug"].pk,)),
        reverse("shop:basket"),
        reverse("shop:faqs"),
    ]


@pytest.mark.parametrize("preview", [True, False])
def test_shop_pages_noindex(client, shop, settings, preview):
    settings.SHOP_PREVIEW = preview
    for url in shop_urls(shop):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert (NOINDEX in resp.content.decode()) == preview, url


def test_other_pages_indexed(client, shop, settings):
    # (just the shop's pages)
    settings.SHOP_PREVIEW = True
    assert NOINDEX not in client.get("/").content.decode()


# SHOP_TEST_MODE: a banner on the shop's pages

TEST_BANNER = '<aside class="shop-test-banner" aria-label="Test mode">'


@pytest.mark.parametrize("test_mode", [True, False])
def test_test_mode_banner(client, shop, settings, test_mode):
    settings.SHOP_TEST_MODE = test_mode
    for url in shop_urls(shop):
        content = " ".join(client.get(url).content.decode().split())
        assert (TEST_BANNER in content) == test_mode, url
        assert ("orders aren't real, and no real payments are taken" in content) == test_mode, url


def test_test_mode_banner_shop_only(client, shop, settings):
    settings.SHOP_TEST_MODE = True
    assert TEST_BANNER not in client.get("/").content.decode()
