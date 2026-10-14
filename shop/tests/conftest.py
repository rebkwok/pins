import pytest

from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    # The basket middleware uses the cache to throttle clearing expired baskets;
    # clear it so tests don't affect each other
    cache.clear()
    yield
    cache.clear()
