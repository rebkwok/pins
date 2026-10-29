from django.conf import settings
from django.utils.functional import SimpleLazyObject

from .models import Sale
from .views import get_existing_basket_quantity


def shop_context(request):
    # basket_quantity and current_sale are lazy, so they are only queried on
    # pages that display them (shop pages)
    return {
        "basket_quantity": SimpleLazyObject(
            lambda: get_existing_basket_quantity(request)
        ),
        "current_sale": SimpleLazyObject(Sale.current_sale),
        # (shop/base.html: not listed by search engines while a hidden preview)
        "shop_preview": settings.SHOP_PREVIEW,
        # (shop/base.html: a banner saying it's in test mode)
        "shop_test_mode": settings.SHOP_TEST_MODE,
    }
