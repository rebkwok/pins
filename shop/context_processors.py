from os import environ

from .models import Sale
from .views import get_basket_quantity


def shop_context(request):
    return {
        "basket_quantity": get_basket_quantity(request),
        "hide_search": environ.get("HIDE_SEARCH", False),
        "current_sale": Sale.current_sale(),
    }
