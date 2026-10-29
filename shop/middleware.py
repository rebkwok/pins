from django.core.cache import cache

from salesman.core.utils import get_salesman_model

Basket = get_salesman_model("Basket")

CLEAR_EXPIRED_BASKETS_CACHE_KEY = "shop:clear_expired_baskets"
# Minimum number of seconds between runs
CLEAR_EXPIRED_BASKETS_INTERVAL = 60


def clear_expired_baskets_middleware(get_response):
    def middleware(request):
        # Clear expired baskets before non-htmx views, at most once per interval.
        # The clear_expired_baskets management command also runs on a cron; this
        # keeps stock up to date between cron runs.
        # cache.add only sets the key (and returns True) if it isn't already set.
        if "Hx-Request" not in request.headers and cache.add(
            CLEAR_EXPIRED_BASKETS_CACHE_KEY, True, CLEAR_EXPIRED_BASKETS_INTERVAL
        ):
            Basket.clear_expired()
        return get_response(request)

    return middleware
