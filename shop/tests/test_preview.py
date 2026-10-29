"""SHOP_PREVIEW: while the shop is a hidden preview, its pages aren't listed by search engines"""

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
