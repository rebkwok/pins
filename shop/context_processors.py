from os import environ

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
        "hide_search": environ.get("HIDE_SEARCH", False),
        "current_sale": SimpleLazyObject(Sale.current_sale),
    }
