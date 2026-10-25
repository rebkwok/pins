import re
from decimal import Decimal

from django import template
from wagtail.models import Page

from shop.models import ShopPage


register = template.Library()


@register.inclusion_tag("shop/tags/shop_breadcrumbs.html", takes_context=True)
def shop_breadcrumbs(context):
    """
    The breadcrumbs for shop pages, as [{"url", "label"}] (the last one is the
    current page, without a url)
    """
    path_to_current_page = {
        "order": "Order Status",
        "basket": "Basket",
        "checkout": "Checkout",
    }

    page = context.get("self")
    current_page = None
    match = re.match(r"^/shop/(?P<current_page>\w+)/.*", context.request.path)
    if match:
        current_page = match.groups("current_page")[0]

    def page_items(page):
        # The page and its ancestors, from Home
        return [
            {"url": ancestor.get_url(context.request), "label": "Home" if index == 0 else ancestor.title}
            for index, ancestor in enumerate(
                Page.objects.ancestor_of(page, inclusive=True).filter(depth__gt=1)
            )
        ]

    items = []
    if current_page in path_to_current_page or current_page == "product":
        # A shop view (not a page), under the shop page
        items = page_items(ShopPage.objects.latest("id"))
        if current_page == "product":
            category = context["product"].category
            items.append({"url": category.get_url(context.request), "label": category.title})
            items.append({"url": None, "label": context["product"].name})
        else:
            items.append({"url": None, "label": path_to_current_page[current_page]})
    elif page is not None and page.depth > 2:
        # (When on the home page, displaying breadcrumbs is irrelevant)
        items = page_items(page)
        items[-1]["url"] = None

    return {"items": items, "request": context.request}


@register.filter
def gbp(value):
    """An amount in pounds, e.g. £5.00, or -£5.00 for negative amounts"""
    if value in (None, ""):
        return ""
    value = Decimal(value)
    sign = "-" if value < 0 else ""
    return f"{sign}£{abs(value):,.2f}"


@register.simple_tag(takes_context=True)
def shop_filter_url(context, **params):
    """
    The current page's address with the shop's search/filter params changed (a
    blank value removes the param), e.g. {% shop_filter_url category="mugs" %}
    """
    query = context["request"].GET.copy()
    for key, value in params.items():
        if value in ("", None):
            query.pop(key, None)
        else:
            query[key] = value
    encoded = query.urlencode()
    return f"?{encoded}" if encoded else "?"
