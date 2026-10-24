from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path
from wagtail import hooks
from wagtail.admin.admin_url_finder import AdminURLFinder
from wagtail.admin.viewsets.base import ViewSet
from wagtail.admin.panels import FieldPanel
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from .admin_orders import OrderViewSet
from .admin_views import SHOP_STOCK_MENU_LABEL, DispatchersView
from .models import (
    PRODUCT_VARIANT_PANELS,
    CategoryPage,
    DiscountCode,
    Product,
    ProductVariant,
    Sale,
    SaleCategory,
    SaleProduct,
    VariantStockHelpPanel,
    protected_variants_message,
)



class ShopStockViewSet(SnippetViewSet):
    """
    A snippet in the Shop Stock menu, with Shop Stock in its breadcrumbs
    (Home > Shop Stock > Products). The menu has no page of its own, so it
    isn't a link.
    """

    @property
    def breadcrumbs_items(self):
        return [*super().breadcrumbs_items, {"url": None, "label": SHOP_STOCK_MENU_LABEL}]


# The default order of the shop stock lists (unless a column is sorted): by
# category (by id too, so categories with the same title aren't mixed together),
# then product, in their shop page order
PRODUCT_ORDERING = (
    "category_page__title",
    "category_page_id",
    "index",
    "name",
)


class ProductViewSet(ShopStockViewSet):
    model = Product
    list_display = (
        "name",
        "category_link",
        "index",
        "dispatcher_display",
        BooleanColumn("live"),
        "get_variant_count",
    )
    list_filter = ("category_page",)

    def get_queryset(self, request):
        return Product.objects.select_related("category_page").order_by(
            *PRODUCT_ORDERING
        )


class ProductVariantViewSet(ShopStockViewSet):
    model = ProductVariant
    # Variants are ordered within their product (on the product's page), so the
    # list doesn't offer reordering all variants together
    sort_order_field = None
    panels = [
        FieldPanel("product"),
        VariantStockHelpPanel(classname="help-block help-info"),
        *PRODUCT_VARIANT_PANELS,
    ]
    list_display = (
        "product",
        "variant_full_name",
        "category_link",
        "base_price",
        "stock_display",
        BooleanColumn("live"),
    )
    list_filter = ("product",)

    def get_queryset(self, request):
        # Each product's variants are listed together, in the product's order
        return ProductVariant.objects.select_related(
            "product__category_page"
        ).order_by(
            *(f"product__{field}" for field in PRODUCT_ORDERING),
            "sort_order",
        )


class SaleViewSet(ShopStockViewSet):
    model = Sale
    list_display = (
        "name",
        "start_date",
        "end_date",
    )


class DiscountCodeViewSet(ShopStockViewSet):
    model = DiscountCode
    icon = "tag"
    list_display = ("code", "amount", "status", "description", "date_created")
    list_filter = ("active",)
    search_fields = ("code", "description")


class DispatchersViewSet(ViewSet):
    """Shop Stock > Dispatchers: the users in the Dispatchers group"""

    name = "shop_dispatchers"
    menu_label = "Dispatchers"
    icon = "group"

    def get_urlpatterns(self):
        return [path("", DispatchersView.as_view(), name="index")]


class ProductGroup(SnippetViewSetGroup):
    menu_label = SHOP_STOCK_MENU_LABEL
    menu_icon = "pick"
    items = (
        ProductViewSet,
        ProductVariantViewSet,
        SaleViewSet,
        DiscountCodeViewSet,
        DispatchersViewSet,
    )
    menu_order = 200


register_snippet(ProductGroup)


@hooks.register("register_admin_viewset")
def register_order_viewset():
    return OrderViewSet()


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


@hooks.register("after_edit_snippet")
def remind_to_check_stock(request, instance):
    """
    A variant (on its own, or in its product's form) has been made live again;
    its stock may be left from before, so remind the admin to check it
    """
    for reminder in getattr(instance, "stock_reminders", []):
        messages.warning(request, reminder)


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

