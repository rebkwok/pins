"""
The dispatcher view: for dispatchers (users in the Dispatchers group), their
own items to send (or hand over, for collection), grouped by order, with a
button to mark each order's items shipped; the items they've sent; and a
spreadsheet of their items to send. It's their only admin page, so the admin
home goes straight to it (see dashboard.middleware).
"""

from itertools import groupby

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import pluralize
from django.urls import path, reverse
from django.utils.timezone import localtime
from django.views.generic import TemplateView
from wagtail.admin import messages
from wagtail.admin.menu import MenuItem
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin
from wagtail.admin.viewsets.base import ViewSet

from common.users import real_users_q

from .admin_orders import OrderItemsExportMixin
from .admin_views import SHOP_SETUP_MENU_LABEL, DispatchersView
from .models import DISPATCHERS_GROUP, Order, OrderItem, dispatcher_name, is_dispatcher

User = get_user_model()

# The orders whose items can be sent (paid)
SHIPPABLE_STATUSES = [
    Order.Status.PROCESSING,
    Order.Status.PARTIALLY_SHIPPED,
    Order.Status.SHIPPED,
    Order.Status.COMPLETED,
]
# Orders' items sent recently, on the Sent tab
SENT_ITEMS_SHOWN = 100


def can_dispatch(user):
    return is_dispatcher(user) or user.is_superuser


def items_to_send(user):
    return (
        OrderItem.objects.filter(
            dispatcher=user,
            shipping_status=OrderItem.TO_SEND,
            order__status__in=SHIPPABLE_STATUSES,
        )
        .select_related("order")
        # oldest orders first
        .order_by("order__date_created", "order_id", "id")
    )


def by_order(items):
    """[(order, [its items])], in the items' order"""
    return [
        (order_items[0].order, order_items)
        for order_items in (
            list(group) for _, group in groupby(items, key=lambda item: item.order_id)
        )
    ]


class DispatchView(OrderItemsExportMixin, WagtailAdminTemplateMixin, TemplateView):
    """
    The dispatcher's items to send (or, with ?sent, the items they've sent).
    With ?dispatcher=<id>, people who can see the Dispatchers page (e.g. shop
    admins) can see a dispatcher's page as they see it, read-only.
    """

    template_name = "shop/admin/dispatch.html"
    page_title = "Items to send"
    header_icon = "mail"

    export_sheet_title = "Items to send"
    list_export = [
        "order.ref",
        "order.date_created",
        "order.name",
        "order.email",
        "order.get_shipping_method_display",
        "order.shipping_address",
        "name",
        "quantity",
    ]
    export_headings = {
        "order.ref": "Order",
        "order.date_created": "Date",
        "order.name": "Customer",
        "order.email": "Email",
        "order.get_shipping_method_display": "Shipping method",
        "order.shipping_address": "Shipping address",
        "name": "Item",
        "quantity": "Quantity",
    }
    def dispatch(self, request, *args, **kwargs):
        if "dispatcher" in request.GET:
            # Someone else's page, read-only
            if not DispatchersView.can_view(request.user) or request.method != "GET":
                raise PermissionDenied
            self.dispatcher = get_object_or_404(
                User.objects.filter(real_users_q(), groups__name=DISPATCHERS_GROUP),
                pk=request.GET["dispatcher"],
            )
            self.read_only = True
        else:
            if not can_dispatch(request.user):
                raise PermissionDenied
            self.dispatcher = request.user
            self.read_only = False
        return super().dispatch(request, *args, **kwargs)

    def get_page_title(self):
        if self.read_only:
            return f"{dispatcher_name(self.dispatcher)}'s items to send"
        return self.page_title

    def url(self, **params):
        """This page's url (for this dispatcher), with params"""
        if self.read_only:
            params = {"dispatcher": self.dispatcher.pk, **params}
        query = "&".join(f"{key}={value}" if value != "" else key for key, value in params.items())
        return reverse("shop_dispatch:index") + (f"?{query}" if query else "")

    def get_breadcrumbs_items(self):
        if self.read_only:
            return self.breadcrumbs_items + [
                {"url": None, "label": SHOP_SETUP_MENU_LABEL},
                {"url": reverse("shop_dispatchers:index"), "label": "Dispatchers"},
                {"url": "", "label": self.get_page_title()},
            ]
        return self.breadcrumbs_items + [{"url": "", "label": self.page_title}]

    def get_filename(self):
        return f"items-to-send-{localtime():%Y-%m-%d-%H%M}"

    def get_heading(self, queryset, field):
        return self.export_headings[field]

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == self.FORMAT_XLSX:
            return self.as_spreadsheet(items_to_send(self.dispatcher), self.FORMAT_XLSX)
        return super().get(request, *args, **kwargs)

    @property
    def showing_sent(self):
        return "sent" in self.request.GET

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.dispatcher
        to_send = list(items_to_send(user))
        context["to_send_count"] = len(to_send)
        context["showing_sent"] = self.showing_sent
        if self.showing_sent:
            sent = OrderItem.objects.filter(
                dispatcher=user, shipping_status=OrderItem.SHIPPED
            ).select_related("order", "shipped_by").order_by(
                "-shipped_at", "-order__date_created", "order_id", "id"
            )[:SENT_ITEMS_SHOWN]
            context["orders"] = by_order(list(sent))
        else:
            context["orders"] = by_order(to_send)
        context["read_only"] = self.read_only
        context["dispatcher"] = self.dispatcher
        context["dispatcher_name"] = dispatcher_name(self.dispatcher)
        context["to_send_url"] = self.url()
        context["sent_url"] = self.url(sent="")
        context["download_url"] = self.url(export="xlsx")
        return context

    def post(self, request, *args, **kwargs):
        # Mark the dispatcher's items in the order shipped (or collected)
        order = get_object_or_404(Order, pk=request.POST.get("order"))
        items = list(items_to_send(request.user).filter(order=order))
        shipped = order.mark_items_shipped(items, request.user) if items else []
        if shipped:
            done = "collected" if order.is_collected else "shipped"
            messages.success(
                request,
                f"Order {order.ref}: {len(shipped)} item{pluralize(len(shipped))} "
                f"marked {done}, and the customer has been emailed.",
            )
        else:
            messages.warning(request, f"Order {order.ref} has nothing for you to send.")
        return redirect("shop_dispatch:index")


class DispatchMenuItem(MenuItem):
    def is_shown(self, request):
        # (for dispatchers, not e.g. superusers who aren't dispatchers)
        return is_dispatcher(request.user)


class DispatchViewSet(ViewSet):
    name = "shop_dispatch"
    url_prefix = "shop/dispatch"
    menu_label = "Items to send"
    icon = "mail"
    menu_item_class = DispatchMenuItem
    add_to_admin_menu = True
    # (with the orders, see dashboard/wagtail_hooks.py)
    menu_order = 505

    def get_urlpatterns(self):
        return [path("", DispatchView.as_view(), name="index")]
