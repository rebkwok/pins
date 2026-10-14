from datetime import datetime, UTC

import pytest

from django.core.cache import cache

from ..middleware import CLEAR_EXPIRED_BASKETS_CACHE_KEY

pytestmark = pytest.mark.django_db


def expire(basket):
    basket.timeout = datetime(2020, 3, 1, tzinfo=UTC)
    basket.save()


def test_basket_middleware(client, basket):
    client.get("/")
    assert basket.items.exists()
    # make basket expired
    expire(basket)
    cache.delete(CLEAR_EXPIRED_BASKETS_CACHE_KEY)
    # middleware clears expired basket
    client.get("/")
    assert not basket.items.exists()


def test_basket_middleware_throttled(client, basket):
    client.get("/")
    expire(basket)
    # middleware ran on the first request, so doesn't run again until the
    # throttle interval has passed
    client.get("/")
    assert basket.items.exists()

    # interval has passed (cache key expired)
    cache.delete(CLEAR_EXPIRED_BASKETS_CACHE_KEY)
    client.get("/")
    assert not basket.items.exists()


def test_basket_middleware_skips_htmx_requests(client, basket):
    expire(basket)
    client.get("/", headers={"Hx-Request": "true"})
    assert basket.items.exists()
    assert cache.get(CLEAR_EXPIRED_BASKETS_CACHE_KEY) is None
