import re

from django import template
from wagtail.models import Page

from shop.models import ShopPage, CategoryPage


register = template.Library()


@register.inclusion_tag("shop/tags/shop_breadcrumbs.html", takes_context=True)
def shop_breadcrumbs(context):
    path_to_current_page = {
        "order": "Order Status",
        "basket": "Basket",
        "checkout": "Checkout",
    }

    self = context.get("self")
    this_page = None
    current_page = None

    match = re.match(r"^/shop/(?P<current_page>\w+)/.*", context.request.path)
    if match:
        current_page = match.groups("current_page")[0]

    if (self is None or self.depth <= 2) and current_page != "product":
        # When on the home page, displaying breadcrumbs is irrelevant.
        # skip this for products so we can add in the category
        ancestors = ()
    else:
        # is it a product or other shop page
        if current_page in path_to_current_page or current_page == "product":
            self = ShopPage.objects.latest("id")
            this_page = path_to_current_page.get(current_page, context["product"].name)

        ancestors = list(
            Page.objects.ancestor_of(self, inclusive=True).filter(depth__gt=1)
        )
        if current_page == "product":
            ancestors.append(context["product"].category_page)

    context_data = {
        "ancestors": ancestors,
        "request": context.request,
        "this_page": this_page,
    }

    return context_data
