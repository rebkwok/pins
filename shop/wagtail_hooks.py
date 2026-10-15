from salesman.admin.wagtail.panels import ReadOnlyPanel
from salesman.admin.wagtail_hooks import OrderAdmin as SalesmanOrderAdmin
from salesman.core.utils import get_salesman_model
from wagtail.admin.ui.tables import BooleanColumn
from wagtail_modeladmin.options import modeladmin_register
from django.contrib import messages
from django.shortcuts import redirect
from wagtail import hooks
from wagtail.admin.admin_url_finder import AdminURLFinder
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from .models import (
    CategoryPage,
    Product,
    ProductVariant,
    Sale,
    SaleCategory,
    SaleProduct,
    protected_variants_message,
)


Order = get_salesman_model("Order")


class ProductViewSet(SnippetViewSet):
    model = Product
    list_display = (
        "name",
        "category_link",
        "index",
        BooleanColumn("live"),
        "get_variant_count",
    )
    list_filter = ("category_page",)


class ProductVariantViewSet(SnippetViewSet):
    model = ProductVariant
    list_display = (
        "product",
        "variant_full_name",
        "category_link",
        "base_price",
        "stock",
        BooleanColumn("live"),
    )
    list_filter = ("product",)


class SaleViewSet(SnippetViewSet):
    model = Sale
    list_display = (
        "name",
        "start_date",
        "end_date",
    )


class ProductGroup(SnippetViewSetGroup):
    menu_label = "Shop Stock"
    menu_icon = "pick"
    items = (ProductViewSet, ProductVariantViewSet, SaleViewSet)
    menu_order = 200


class OrderAdmin(SalesmanOrderAdmin):
    SalesmanOrderAdmin.list_display.insert(2, "name")
    SalesmanOrderAdmin.list_display.insert(4, "shipping_method")
    SalesmanOrderAdmin.search_fields.append("name")
    SalesmanOrderAdmin.default_panels[2].children.insert(2, ReadOnlyPanel("name"))
    SalesmanOrderAdmin.default_panels[2].children.insert(
        3, ReadOnlyPanel("shipping_method")
    )
    menu_order = 250


register_snippet(ProductGroup)
modeladmin_register(OrderAdmin)


def _protected_variants_response(request, variants, obj):
    """
    If any of the variants have been ordered or are in customers' baskets, show a
    message and redirect to obj's edit page, rather than deleting (which would
    raise ProtectedError, a server error in the admin)
    """
    message = protected_variants_message(variants)
    if message:
        messages.error(request, message)
        return redirect(
            AdminURLFinder(request.user).get_edit_url(obj)
            or request.META.get("HTTP_REFERER", "/")
        )


@hooks.register("before_delete_snippet")
def protect_variants(request, instances):
    variants = []
    for instance in instances:
        if isinstance(instance, ProductVariant):
            variants.append(instance)
        elif isinstance(instance, Product):
            variants.extend(instance.variants.all())
    if variants:
        return _protected_variants_response(request, variants, instances[0])


@hooks.register("before_delete_page")
def protect_category_variants(request, page):
    # Deleting a shop or category page deletes its categories' products
    categories = CategoryPage.objects.descendant_of(page, inclusive=True)
    variants = ProductVariant.objects.filter(product__category_page__in=categories)
    if variants.exists():
        return _protected_variants_response(request, variants, page)

