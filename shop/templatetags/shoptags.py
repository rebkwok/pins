import re

from django import template
from wagtail.models import Page

from shop.models import ShopPage


register = template.Library()


@register.inclusion_tag("shop/tags/shop_breadcrumbs.html", takes_context=True)
def shop_breadcrumbs(context):
    page = ShopPage.objects.latest("id")
    path_to_current_page = {
        "order": "Order Status",
        "basket": "Basket",
        "checkout": "Checkout",
    }

    match = re.match(r"^/shop/(?P<current_page>\w+)/.*", context.request.path)
    if match:
        current_page = match.groups("current_page")[0]
        if current_page == "category":
            this_page = context["category"].name
        else:
            this_page = path_to_current_page[current_page]
    else:
        this_page = None
    ancestors = Page.objects.ancestor_of(page, inclusive=True).filter(depth__gt=1)
    context_data = {
        "ancestors": ancestors,
        "request": context.request,
        "this_page": this_page,
    }
    return context_data
