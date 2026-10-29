"""
Shop admin > Shop activity: the shop's entries in Wagtail's audit log (see
activity.py), like Reports > Site history but just the shop's: its products,
variants, categories, sales, discount codes, orders and settings, and
dispatchers added or removed. For shop admins (and superusers); shop managers
see each order's activity on its page.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import IntegerField, Value
from django.urls import path
from wagtail.admin.menu import MenuItem
from wagtail.admin.views.reports.audit_logging import (
    LogEntriesView,
    SiteHistoryReportFilterSet,
)
from wagtail.admin.viewsets.base import ViewSet
from wagtail.log_actions import registry as log_registry
from wagtail.models import ModelLogEntry

from . import activity
from .admin_views import SHOP_ADMIN_MENU_LABEL, DispatchersView
from .models import (
    Category,
    DiscountCode,
    Order,
    Product,
    ProductVariant,
    Sale,
    ShippingRate,
    ShopFAQ,
    ShopSettings,
)

SHOP_MODELS = (
    Product,
    ProductVariant,
    Category,
    Sale,
    DiscountCode,
    ShippingRate,
    ShopFAQ,
    Order,
    ShopSettings,
)
DISPATCHER_ACTIONS = (activity.DISPATCHER_ADDED, activity.DISPATCHER_REMOVED)

# Who can see the page: shop admins (who manage the shop's stock)
VIEW_PERMISSION = "shop.change_product"


def can_view(user):
    return user.has_perm(VIEW_PERMISSION)


def shop_log_entries(user):
    """
    The shop's log entries that the user can see (as in the site history: those
    for the kinds of items they have permissions for)
    """
    content_types = ContentType.objects.get_for_models(*SHOP_MODELS).values()
    entries = ModelLogEntry.objects.viewable_by_user(user).filter(
        content_type__in=content_types
    )
    if DispatchersView.can_view(user):
        # (logged on the users, which shop admins can't manage)
        entries = entries | ModelLogEntry.objects.filter(action__in=DISPATCHER_ACTIONS)
    return entries


class ShopActivityFilterSet(SiteHistoryReportFilterSet):
    """The site history's filters, with just the shop's choices"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        entries = shop_log_entries(self.request.user)
        self.filters["object_type"].queryset = ContentType.objects.filter(
            pk__in=entries.values("content_type")
        ).order_by("model")

    def get_action_choices(self):
        actions = set(shop_log_entries(self.request.user).get_actions())
        return [choice for choice in log_registry.get_choices() if choice[0] in actions]

    def get_users_queryset(self):
        # (the site history's filters take them from page log entries)
        return shop_log_entries(self.request.user).get_users()


class ShopActivityView(LogEntriesView):
    page_title = "Shop activity"
    # (the site history's results, as cards on phones)
    results_template_name = "shop/admin/activity_results.html"
    header_icon = "history"
    filterset_class = ShopActivityFilterSet
    index_url_name = "shop_activity:index"
    index_results_url_name = "shop_activity:results"

    def dispatch(self, request, *args, **kwargs):
        if not can_view(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return [
            *self.breadcrumbs_items,
            {"url": None, "label": SHOP_ADMIN_MENU_LABEL},
            {"url": "", "label": self.page_title},
        ]

    def get_filename(self):
        return super().get_filename().replace("audit-log", "shop-activity")

    def get_filtered_queryset(self):
        # (one log model, so no union of models as in LogEntriesView)
        self.log_models = [ModelLogEntry]
        queryset = (
            shop_log_entries(self.request.user)
            .values("pk", "timestamp")
            .annotate(log_model_index=Value(0, output_field=IntegerField()))
        )
        return self.filter_queryset(queryset).order_by("-timestamp")


class ShopActivityMenuItem(MenuItem):
    def is_shown(self, request):
        return can_view(request.user)


class ShopActivityViewSet(ViewSet):
    name = "shop_activity"
    menu_label = "Shop activity"
    icon = "history"
    menu_item_class = ShopActivityMenuItem

    def get_urlpatterns(self):
        return [
            path("", ShopActivityView.as_view(), name="index"),
            path("results/", ShopActivityView.as_view(results_only=True), name="results"),
        ]
