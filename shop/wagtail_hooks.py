from django.contrib import messages
from django.shortcuts import redirect
from django.template.defaultfilters import pluralize
from django.urls import path, reverse
from wagtail import hooks
from wagtail.admin.admin_url_finder import AdminURLFinder
from wagtail.admin.viewsets.base import ViewSet
from wagtail.admin.panels import FieldPanel
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.chooser import SnippetChooserViewSet
from wagtail.admin.search import SearchArea
from wagtail.permission_policies import ModelPermissionPolicy
from wagtail.snippets.views.snippets import IndexView as SnippetIndexView
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from common.admin_menu import PermissionMenuItem

from .admin_orders import OrderPermissionPolicy, OrderViewSet
from .admin_views import SHOP_STOCK_MENU_LABEL, DispatchersView
from .models import (
    PRODUCT_VARIANT_PANELS,
    Category,
    DiscountCode,
    Order,
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
# category, then product, in their shop page order
PRODUCT_ORDERING = (
    "category__sort_order",
    "category__title",
    "index",
    "name",
)


class CategoryChooserViewSet(SnippetChooserViewSet):
    # A "Create" tab in the chooser (e.g. the product's category), so a
    # category can be added without leaving the product. (Just the title: the
    # description's rich text editor doesn't work in the chooser; it can be
    # added on the category's own page.)
    form_fields = ["title"]
    create_action_label = "Add a category"


class CategoryViewSet(ShopStockViewSet):
    model = Category
    icon = "folder-open-inverse"
    # Dragged into their order on the shop page
    sort_order_field = "sort_order"
    list_display = ("title", "get_product_count", "url_display")
    search_fields = ("title",)
    chooser_viewset_class = CategoryChooserViewSet


class ProductIndexView(SnippetIndexView):
    # Searches from the sidebar start here (see register_products_search_area),
    # so offer the same search in the other areas (e.g. orders)
    show_other_searches = True


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
    list_filter = ("category",)
    search_fields = ("name", "category__title")
    index_view_class = ProductIndexView

    def get_queryset(self, request):
        return Product.objects.select_related("category").order_by(
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
    search_fields = ("product__name", "variant_name", "colour", "size")

    def get_queryset(self, request):
        # Each product's variants are listed together, in the product's order
        return ProductVariant.objects.select_related(
            "product__category"
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
    search_fields = ("name",)


class DiscountCodeViewSet(ShopStockViewSet):
    model = DiscountCode
    icon = "tag"
    list_display = ("code", "amount", "status", "description", "date_created")
    list_filter = ("active",)
    search_fields = ("code", "description")


class DispatchersMenuItem(PermissionMenuItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, permission=DispatchersView.permission, **kwargs)


class DispatchersViewSet(ViewSet):
    """Shop Stock > Dispatchers: the users in the Dispatchers group"""

    name = "shop_dispatchers"
    menu_label = "Dispatchers"
    icon = "group"

    @property
    def menu_item_class(self):
        # Only for users who can change users' groups (site admins), like the
        # page itself
        return DispatchersMenuItem

    def get_urlpatterns(self):
        return [path("", DispatchersView.as_view(), name="index")]


class ShopSettingsMenuItem(PermissionMenuItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, permission="shop.change_shopsettings", **kwargs)


class ShopSettingsViewSet(ViewSet):
    """
    Shop Stock > Shop settings: a link to the shop settings (a Wagtail setting,
    removed from the Settings menu so they're with the rest of the shop)
    """

    name = "shop_settings"
    menu_label = "Shop settings"
    icon = "cogs"
    menu_item_class = ShopSettingsMenuItem

    @property
    def menu_url(self):
        return reverse("wagtailsettings:edit", args=("shop", "shopsettings"))

    def get_urlpatterns(self):
        return []


@hooks.register("construct_settings_menu")
def hide_shop_settings(request, menu_items):
    # (in the Shop Stock menu instead)
    menu_items[:] = [item for item in menu_items if item.name != "shop-settings"]


class ProductGroup(SnippetViewSetGroup):
    menu_label = SHOP_STOCK_MENU_LABEL
    menu_icon = "pick"
    items = (
        CategoryViewSet,
        ProductViewSet,
        ProductVariantViewSet,
        SaleViewSet,
        DiscountCodeViewSet,
        ShopSettingsViewSet,
        DispatchersViewSet,
    )
    menu_order = 200


register_snippet(ProductGroup)


class PermissionSearchArea(SearchArea):
    """An admin search area for users with any of the actions' permissions"""

    def __init__(self, *args, permission_policy, actions, **kwargs):
        super().__init__(*args, **kwargs)
        self.permission_policy = permission_policy
        self.actions = actions

    def is_shown(self, request):
        return self.permission_policy.user_has_any_permission(request.user, self.actions)


# Shop staff can't search pages, so the sidebar's search (the first search area
# they can use) searches products (or orders), rather than images. Pages
# (order 100) are still first for page editors.


@hooks.register("register_admin_search_area")
def register_products_search_area():
    return PermissionSearchArea(
        "Products",
        reverse("wagtailsnippets_shop_product:list"),
        icon_name="pick",
        order=150,
        permission_policy=ModelPermissionPolicy(Product),
        actions=["add", "change", "delete", "view"],
    )


@hooks.register("register_admin_search_area")
def register_orders_search_area():
    return PermissionSearchArea(
        "Orders",
        reverse("shop_orders:index"),
        icon_name="list-ul",
        order=160,
        permission_policy=OrderPermissionPolicy(Order),
        actions=["change"],
    )


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


@hooks.register("before_delete_snippet")
def protect_categories(request, instances):
    """Categories with products can't be deleted"""
    with_products = [
        instance
        for instance in instances
        if isinstance(instance, Category) and instance.products.exists()
    ]
    if with_products:
        messages.error(
            request,
            f"{', '.join(str(category) for category in with_products)} can't be "
            "deleted: move "
            f"{pluralize(len(with_products), 'its,their')} products to another "
            "category, or delete them, first.",
        )
        return redirect(
            AdminURLFinder(request.user).get_edit_url(with_products[0])
            if len(with_products) == 1
            else reverse("wagtailsnippets_shop_category:list")
        )

