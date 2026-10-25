from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Min, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.template.defaultfilters import pluralize
from django.utils import timezone
from django.views.generic import TemplateView
from wagtail.admin import messages
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin
from wagtail.admin.views.generic.ordering import ReorderView
from wagtail.log_actions import log
from wagtail.permission_policies import ModelPermissionPolicy

from common.users import real_users_q

from . import activity
from .models import (
    DISPATCHERS_GROUP,
    SHIPPING_COLLECT,
    Order,
    OrderItem,
    Product,
    dispatcher_name,
)

User = get_user_model()

# The admin menu that the shop's stock, sales, discount codes and dispatchers are in
# The admin menus: what's sold, and the shop's promotions and settings
SHOP_STOCK_MENU_LABEL = "Shop stock"
SHOP_ADMIN_MENU_LABEL = "Shop admin"

# The statuses of orders whose items can be sent (once they've been paid)
SHIPPABLE_STATUSES = [
    Order.Status.PROCESSING,
    Order.Status.PARTIALLY_SHIPPED,
    Order.Status.SHIPPED,
    Order.Status.COMPLETED,
]


class CategoryProductsReorderView(ReorderView):
    """
    Move one of a category's products to a new position in the category (from
    the category's page, see models.CategoryProductsPanel)
    """

    model = Product
    sort_order_field = "sort_order"
    permission_policy = ModelPermissionPolicy(Product)

    def get_queryset(self):
        return Product.objects.filter(category_id=self.kwargs["category_pk"]).order_by(
            "sort_order", "name"
        )

    def post(self, request, *args, **kwargs):
        product = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            position = request.GET.get("position")
            log(
                product.category,
                activity.CATEGORY_REORDERED,
                data={
                    "product": product.name,
                    "position": int(position) + 1 if position and position.isdigit() else "",
                },
            )
        return response


class AddDispatcherForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="User",
        empty_label="Choose a user",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            User.objects.filter(is_active=True)
            .exclude(groups__name=DISPATCHERS_GROUP)
            .filter(real_users_q())
            .order_by("first_name", "last_name", "username")
        )
        self.fields["user"].label_from_instance = (
            lambda user: f"{dispatcher_name(user)} ({user.email})"
            if user.email
            else dispatcher_name(user)
        )


class DispatchersView(WagtailAdminTemplateMixin, TemplateView):
    """
    Dispatcher activity: the users in the Dispatchers group, with their products
    and the items they still have to send (or hold for collection), so shop
    admins and Orders only users can check that orders are being sent; and the
    items of products without a dispatcher. Site admins (who can change users,
    and so their groups) can add existing users to the group and remove them.
    """

    template_name = "shop/admin/dispatchers.html"
    page_title = "Dispatcher activity"
    header_icon = "group"

    # (changing a user's groups needs permission to change users)
    manage_permission = "auth.change_user"
    # shop admins (who choose products' dispatchers) and Orders only users
    view_permissions = ("shop.change_product", "shop.view_order")
    # The oldest pending order is highlighted if it's older than this
    OVERDUE_DAYS = 3

    @classmethod
    def can_view(cls, user):
        return user.has_perm(cls.manage_permission) or any(
            user.has_perm(permission) for permission in cls.view_permissions
        )

    @property
    def can_manage(self):
        return self.request.user.has_perm(self.manage_permission)

    def dispatch(self, request, *args, **kwargs):
        if not self.can_view(request.user):
            raise PermissionDenied
        if request.method == "POST" and not self.can_manage:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return self.breadcrumbs_items + [{"url": "", "label": self.page_title}]

    def pending(self):
        """
        Items still to send or collect, by dispatcher id (None for products
        without a dispatcher): {"to_send", "to_collect", "count", "oldest",
        "overdue"}
        """
        pending = {}
        rows = (
            OrderItem.objects.filter(
                shipping_status=OrderItem.TO_SEND, order__status__in=SHIPPABLE_STATUSES
            )
            .values("dispatcher")
            .annotate(
                to_collect=Count("id", filter=Q(order__shipping_method=SHIPPING_COLLECT)),
                count=Count("id"),
                oldest=Min("order__date_created"),
            )
        )
        overdue = timezone.now() - timedelta(days=self.OVERDUE_DAYS)
        for row in rows:
            pending[row["dispatcher"]] = {
                **row,
                "to_send": row["count"] - row["to_collect"],
                "overdue": row["oldest"] < overdue,
            }
        return pending

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pending = self.pending()
        context["pending_without_dispatcher"] = pending.get(None)
        context["overdue_days"] = self.OVERDUE_DAYS
        dispatchers = list(
            User.objects.filter(real_users_q(), groups__name=DISPATCHERS_GROUP)
            .prefetch_related(
                Prefetch(
                    "dispatched_products",
                    queryset=Product.objects.select_related("category").order_by(
                        "category__sort_order", "category__title", "sort_order", "name"
                    ),
                )
            )
            .order_by("first_name", "last_name", "username")
        )
        items_url = reverse("shop_dispatch:index")
        for dispatcher in dispatchers:
            dispatcher.pending = pending.get(dispatcher.pk)
            dispatcher.pending_url = f"{items_url}?dispatcher={dispatcher.pk}"
        context["pending_without_dispatcher_url"] = (
            reverse("shop_orders:index") + "?no_dispatcher=true"
        )
        context["dispatchers"] = dispatchers
        context["can_manage"] = self.can_manage
        if self.can_manage:
            context["form"] = kwargs.get("form") or AddDispatcherForm()
        return context

    def post(self, request, *args, **kwargs):
        group = Group.objects.get(name=DISPATCHERS_GROUP)
        if "remove" in request.POST:
            user = get_object_or_404(User, pk=request.POST["remove"], groups=group)
            user.groups.remove(group)
            log(user, activity.DISPATCHER_REMOVED)
            message = f"{dispatcher_name(user)} isn't a dispatcher any more."
            product_count = user.dispatched_products.count()
            if product_count:
                message += (
                    f" {product_count} product{pluralize(product_count)} still "
                    f"{pluralize(product_count, 'has,have')} them as dispatcher: "
                    "choose another dispatcher for "
                    f"{pluralize(product_count, 'it,them')}."
                )
                messages.warning(request, message)
            else:
                messages.success(request, message)
            return redirect("shop_dispatchers:index")
        form = AddDispatcherForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        user = form.cleaned_data["user"]
        user.groups.add(group)
        log(user, activity.DISPATCHER_ADDED)
        messages.success(request, f"{dispatcher_name(user)} is now a dispatcher.")
        return redirect("shop_dispatchers:index")
