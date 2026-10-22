from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path
from django.utils.translation import gettext_lazy as _
from salesman.admin.utils import format_price
from salesman.admin.wagtail.panels import OrderAdminPanel, ReadOnlyPanel
from salesman.admin.wagtail_hooks import OrderAdmin as SalesmanOrderAdmin
from salesman.core.utils import get_salesman_model
from wagtail import hooks
from wagtail.admin.admin_url_finder import AdminURLFinder
from wagtail.admin.viewsets.base import ViewSet
from wagtail.admin.panels import FieldPanel, MultiFieldPanel, ObjectList, TabbedInterface
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail_modeladmin.options import modeladmin_register

from .admin_views import SHOP_STOCK_MENU_LABEL, DispatchersView, OrderRefundView
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


Order = get_salesman_model("Order")


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


def _with_name_and_shipping_method(contact_panel):
    """
    A copy of salesman's order Contact panel, with the order name and shipping
    method added after the customer and email
    """
    children = list(contact_panel.children)
    children[2:2] = [
        ReadOnlyPanel("name"),
        ReadOnlyPanel(
            "shipping_method",
            # Show the label (e.g. "Collect in person") rather than the value
            formatter=lambda value, order, request: order.get_shipping_method_display(),
        ),
    ]
    return MultiFieldPanel(children, heading=contact_panel.heading)


def _with_refunds(panel, attr):
    """
    A copy of one of salesman's order panels, with the refunds panel added
    after the panel for attr
    """
    children = list(panel.children)
    index = [getattr(child, "attr", None) for child in children].index(attr) + 1
    children.insert(index, OrderAdminPanel("refunds_display"))
    return MultiFieldPanel(children, heading=panel.heading)


def _order_panel(index, panel):
    if index == 1:
        # Status
        return _with_refunds(panel, "is_paid")
    if index == 2:
        # Contact
        return _with_name_and_shipping_method(panel)
    if index == 3:
        # Totals
        return _with_refunds(panel, "amount_paid_display")
    return panel


class OrderRefundsFilter(admin.SimpleListFilter):
    title = _("Refunds")
    parameter_name = "refunds"

    def lookups(self, request, model_admin):
        return [
            ("partial", _("Partially refunded")),
            ("full", _("Fully refunded")),
            ("none", _("Not refunded")),
        ]

    def queryset(self, request, queryset):
        status = {
            "partial": "Partially refunded",
            "full": "Fully refunded",
            "none": "",
        }.get(self.value())
        if status is None:
            return None
        # The order admin's queryset prefetches the payments
        return queryset.filter(
            id__in=[order.id for order in queryset if order.refund_status == status]
        )


class OrderAdmin(SalesmanOrderAdmin):
    """
    Salesman's order admin, with the order name and shipping method added.
    These build new lists and panels, rather than changing salesman's.
    """

    # After email, and after status
    list_display = [
        *SalesmanOrderAdmin.list_display[:2],
        "name",
        SalesmanOrderAdmin.list_display[2],
        "shipping_method",
        *SalesmanOrderAdmin.list_display[3:5],
        "refunds_list_display",
        *SalesmanOrderAdmin.list_display[5:],
    ]
    list_filter = [
        *SalesmanOrderAdmin.list_filter[:2],
        OrderRefundsFilter,
        *SalesmanOrderAdmin.list_filter[2:],
    ]
    search_fields = [*SalesmanOrderAdmin.search_fields, "name"]

    # Salesman's default_edit_handler is built from its default panels, so this
    # replaces it (salesman's get_edit_handler uses edit_handler if it's set)
    default_panels = [
        _order_panel(index, panel)
        for index, panel in enumerate(SalesmanOrderAdmin.default_panels)
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(default_panels, heading=_("Summary")),
            ObjectList(SalesmanOrderAdmin.default_items_panels, heading=_("Items")),
            ObjectList(
                SalesmanOrderAdmin.default_payments_panels, heading=_("Payments")
            ),
            ObjectList(SalesmanOrderAdmin.default_notes_panels, heading=_("Notes")),
        ]
    )
    # Refunds the order without salesman's orders API
    refund_view_class = OrderRefundView

    def amount_paid_display(self, obj):
        # Refunds are shown separately
        return format_price(obj.amount_received, order=obj, request=self.request)

    amount_paid_display.short_description = _("Amount paid")

    def refunds_display(self, obj):
        if not obj.amount_refunded:
            return "-"
        amount = format_price(obj.amount_refunded, order=obj, request=self.request)
        return f"{amount} ({obj.refund_status.lower()})"

    refunds_display.short_description = _("Refunded")

    def refunds_list_display(self, obj):
        return obj.refund_status

    refunds_list_display.short_description = _("Refunds")

    def get_queryset(self, request):
        # The refunds column uses the payments
        return super().get_queryset(request).prefetch_related("payments")
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

