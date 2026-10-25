from django.contrib import messages
from django.shortcuts import redirect
from django.template.defaultfilters import pluralize
from django.templatetags.static import static
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from wagtail import hooks
from wagtail.admin.admin_url_finder import AdminURLFinder
from wagtail.admin.menu import MenuItem
from wagtail.admin.viewsets.base import ViewSet
from wagtail.admin.panels import FieldPanel
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.log_actions import log
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.chooser import SnippetChooserViewSet
from wagtail.admin.search import SearchArea
from wagtail.admin.ui.components import Component
from wagtail.permission_policies import ModelPermissionPolicy
from wagtail.snippets.views.snippets import EditView as SnippetEditView
from wagtail.snippets.views.snippets import IndexView as SnippetIndexView
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from common.admin_menu import PermissionMenuItem

from .admin_dispatch import DispatchViewSet
from .admin_orders import OrderPermissionPolicy, OrderViewSet
from .admin_views import (
    SHOP_SETUP_MENU_LABEL,
    SHOP_STOCK_MENU_LABEL,
    CategoryProductsReorderView,
    DispatchersView,
)
from . import activity
from .models import (
    PRODUCT_VARIANT_PANELS,
    Category,
    NO_NOTIFY_ADDRESSES_WARNING,
    DiscountCode,
    Order,
    ShopSettings,
    Product,
    ProductVariant,
    Sale,
    SaleCategory,
    SaleProduct,
    VariantStockHelpPanel,
    protected_variants_message,
)



class ShopEditView(SnippetEditView):
    """
    Edit a shop item, logging what changed (e.g. "Price: £10.00 → £12.00", see
    activity.form_changes) instead of Wagtail's plain "Edited"; nothing is
    logged if nothing changed. (The shop's snippets don't have revisions or
    drafts.)
    """

    def save_instance(self):
        changes = activity.form_changes(self.form)
        instance = self.form.save()
        self.has_content_changes = self.form.has_changed()
        self.new_revision = None
        if changes:
            log(instance=instance, action=activity.EDITED, data={"changes": changes})
        return instance


class ShopViewSet(SnippetViewSet):
    """
    A snippet in one of the shop menus, with the menu in its breadcrumbs
    (e.g. Home > Shop stock > Products). The menu has no page of its own, so it
    isn't a link.
    """

    shop_menu_label = SHOP_STOCK_MENU_LABEL
    edit_view_class = ShopEditView

    @property
    def breadcrumbs_items(self):
        return [*super().breadcrumbs_items, {"url": None, "label": self.shop_menu_label}]


# The default order of the shop stock lists (unless a column is sorted): by
# category, then product, in their shop page order
PRODUCT_ORDERING = (
    "category__sort_order",
    "category__title",
    "sort_order",
    "name",
)


class CategoryChooserViewSet(SnippetChooserViewSet):
    # A "Create" tab in the chooser (e.g. the product's category), so a
    # category can be added without leaving the product. (Just the title: the
    # description's rich text editor doesn't work in the chooser; it can be
    # added on the category's own page.)
    form_fields = ["title"]
    create_action_label = "Add a category"


class CategoryViewSet(ShopViewSet):
    model = Category
    icon = "folder-open-inverse"
    # Dragged into their order on the shop page
    sort_order_field = "sort_order"
    list_display = ("title", "products_link", "shop_link")
    search_fields = ("title",)
    chooser_viewset_class = CategoryChooserViewSet


def category_crumb(category):
    """A breadcrumb for a category: its products in the Products list"""
    return {
        "url": f"{reverse('wagtailsnippets_shop_product:list')}?category={category.pk}",
        "label": category.title,
    }


class ProductEditView(ShopEditView):
    """Breadcrumbs: Home > Shop stock > Products > category > product"""

    def get_breadcrumbs_items(self):
        items = super().get_breadcrumbs_items()
        return [*items[:-1], category_crumb(self.object.category), items[-1]]


class ProductVariantEditView(ShopEditView):
    """
    Breadcrumbs: Home > Shop stock > Product variants > category > product >
    variant
    """

    def get_breadcrumbs_items(self):
        items = super().get_breadcrumbs_items()
        product = self.object.product
        return [
            *items[:-1],
            category_crumb(product.category),
            {
                "url": reverse("wagtailsnippets_shop_product:edit", args=(product.pk,)),
                "label": product.name,
            },
            # (the variant, without its product's name)
            {**items[-1], "label": self.object.variant_full_name() or "Variant"},
        ]


class ProductIndexView(SnippetIndexView):
    # Searches from the sidebar start here (see register_products_search_area),
    # so offer the same search in the other areas (e.g. orders)
    show_other_searches = True


class ProductViewSet(ShopViewSet):
    model = Product
    list_display = (
        "name",
        "category_link",
        "dispatcher_display",
        BooleanColumn("live"),
        "variants_link",
    )
    list_filter = ("category",)
    search_fields = ("name", "category__title")
    index_view_class = ProductIndexView
    edit_view_class = ProductEditView

    def get_queryset(self, request):
        return Product.objects.select_related("category").order_by(
            *PRODUCT_ORDERING
        )


class ProductVariantViewSet(ShopViewSet):
    model = ProductVariant
    # Variants are ordered within their product (on the product's page), so the
    # list doesn't offer reordering all variants together
    sort_order_field = None
    panels = [
        FieldPanel("product"),
        VariantStockHelpPanel(),
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
    edit_view_class = ProductVariantEditView

    def get_queryset(self, request):
        # Each product's variants are listed together, in the product's order
        return ProductVariant.objects.select_related(
            "product__category"
        ).order_by(
            *(f"product__{field}" for field in PRODUCT_ORDERING),
            "sort_order",
        )


class SaleViewSet(ShopViewSet):
    model = Sale
    shop_menu_label = SHOP_SETUP_MENU_LABEL
    list_display = (
        "name",
        "start_date",
        "end_date",
    )
    search_fields = ("name",)


class DiscountCodeViewSet(ShopViewSet):
    model = DiscountCode
    shop_menu_label = SHOP_SETUP_MENU_LABEL
    icon = "tag"
    list_display = ("code", "amount", "status", "description", "date_created")
    list_filter = ("active",)
    search_fields = ("code", "description")


class DispatchersMenuItem(MenuItem):
    def is_shown(self, request):
        return DispatchersView.can_view(request.user)


class DispatchersViewSet(ViewSet):
    """Shop setup > Dispatchers: the users in the Dispatchers group"""

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
    Shop setup > Shop settings: a link to the shop settings (a Wagtail setting,
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


class NoNotifyAddressesPanel(Component):
    """On the admin home: a warning if nobody is emailed about new orders"""

    name = "shop_no_notify_addresses"
    order = 10

    def render_html(self, parent_context=None):
        return format_html(
            '<div class="help-block help-warning w-mb-8"><p>{} <a href="{}">Shop settings</a></p></div>',
            NO_NOTIFY_ADDRESSES_WARNING.replace("'Email new orders to'", "the shop settings"),
            reverse("wagtailsettings:edit", args=("shop", "shopsettings")),
        )


@hooks.register("construct_homepage_panels")
def warn_about_no_notify_addresses(request, panels):
    if request.user.has_perm("shop.change_shopsettings") and not (
        ShopSettings.load(request_or_site=request).notify_email_addresses
    ):
        panels.append(NoNotifyAddressesPanel())


@hooks.register("register_admin_urls")
def register_category_products_reorder_url():
    return [
        path(
            "shop/categories/<int:category_pk>/products/reorder/<int:pk>/",
            CategoryProductsReorderView.as_view(),
            name="shop_category_products_reorder",
        )
    ]


@hooks.register("register_log_actions")
def register_shop_log_actions(actions):
    # The shop's activity log entries (orders, dispatchers, ...)
    activity.register(actions)


@hooks.register("insert_global_admin_js")
def shop_admin_js():
    # The product page's stock fields: only those that apply (the script does
    # nothing on other pages)
    return format_html(
        '<script src="{}" defer></script>', static("shop/js/admin_stock_fields.js")
    )


@hooks.register("insert_global_admin_css")
def shop_admin_css():
    # Fields in a row (e.g. a variant's price, stock and items per pack) line up
    # whatever the length of their help text: their labels at the top, and
    # their inputs at the bottom
    return mark_safe(
        """<style>
        .shop-field-row .w-field-row > .w-panel__wrapper,
        .shop-field-row .w-field-row > .w-panel__wrapper > .w-field__wrapper,
        .shop-field-row .w-field { display: flex; flex-direction: column; }
        .shop-field-row .w-field-row > .w-panel__wrapper > .w-field__wrapper,
        .shop-field-row .w-field { flex-grow: 1; }
        .shop-field-row .w-field__input { margin-top: auto; }
        </style>"""
    )


@hooks.register("construct_settings_menu")
def hide_shop_settings(request, menu_items):
    # (in the Shop setup menu instead)
    menu_items[:] = [item for item in menu_items if item.name != "shop-settings"]


class ShopStockGroup(SnippetViewSetGroup):
    """What's sold in the shop"""

    menu_label = SHOP_STOCK_MENU_LABEL
    menu_icon = "pick"
    items = (CategoryViewSet, ProductViewSet, ProductVariantViewSet)
    # (after Orders, see dashboard/wagtail_hooks.py)
    menu_order = 520


class ShopSetupGroup(SnippetViewSetGroup):
    """The shop's promotions and settings"""

    menu_label = SHOP_SETUP_MENU_LABEL
    menu_icon = "cogs"
    items = (SaleViewSet, DiscountCodeViewSet, ShopSettingsViewSet, DispatchersViewSet)
    menu_order = 530


register_snippet(ShopStockGroup)
register_snippet(ShopSetupGroup)


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


@hooks.register("register_admin_viewset")
def register_dispatch_viewset():
    return DispatchViewSet()


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
    # e.g. a product's items still to send moved to its new dispatcher
    for message in getattr(instance, "admin_messages", []):
        messages.info(request, message)


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

