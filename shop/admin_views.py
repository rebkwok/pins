from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import pluralize
from django.views.generic import TemplateView
from wagtail.admin import messages
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin
from salesman.admin.wagtail.views import OrderRefundView as SalesmanOrderRefundView

from .models import DISPATCHERS_GROUP, dispatcher_name
from .payment import PayByStripe

User = get_user_model()

# The admin menu that the shop's stock, sales, discount codes and dispatchers are in
SHOP_STOCK_MENU_LABEL = "Shop Stock"


class OrderRefundView(SalesmanOrderRefundView):
    """
    Refund an order from the orders admin. Salesman's refund view does the refund
    by calling its orders API from javascript, which isn't exposed (see
    pins/urls.py), so this refunds the order when the confirmation form is
    posted. Only full refunds are made here; partial refunds are made in the
    Stripe dashboard.
    """

    def get_template_names(self):
        return ["shop/admin/order_refund.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.instance
        context["stripe_payments"] = order.payments.filter(
            payment_method=PayByStripe.identifier, amount__gt=0
        )
        context["refund_amount"] = order.amount_paid
        return context

    def post(self, request, *args, **kwargs):
        order = self.instance
        if order.status == order.Status.REFUNDED:
            messages.error(request, f"Order {order} has already been refunded.")
            return redirect(self.edit_url)
        refunded, errors = PayByStripe.refund_order(order)
        if refunded:
            messages.success(
                request,
                f"£{refunded:.2f} refunded for order {order}. Stock hasn't been "
                "changed; update it manually if items are going back into stock.",
            )
        for error in errors:
            messages.error(request, f"Error refunding order {order}: {error}")
        if not refunded and not errors:
            messages.warning(request, f"Order {order} has no Stripe payments to refund.")
        return redirect(self.edit_url)


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
            .order_by("first_name", "last_name", "username")
        )
        self.fields["user"].label_from_instance = (
            lambda user: f"{dispatcher_name(user)} ({user.email})"
            if user.email
            else dispatcher_name(user)
        )


class DispatchersView(WagtailAdminTemplateMixin, TemplateView):
    """
    Shop Stock > Dispatchers: the users in the Dispatchers group, with forms to
    add existing users to the group and remove them. (Changing a user's groups
    needs permission to change users.)
    """

    template_name = "shop/admin/dispatchers.html"
    page_title = "Dispatchers"
    header_icon = "group"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perm("auth.change_user"):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return self.breadcrumbs_items + [
            {"url": None, "label": SHOP_STOCK_MENU_LABEL},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["dispatchers"] = (
            User.objects.filter(groups__name=DISPATCHERS_GROUP)
            .annotate(product_count=Count("dispatched_products"))
            .order_by("first_name", "last_name", "username")
        )
        context["form"] = kwargs.get("form") or AddDispatcherForm()
        return context

    def post(self, request, *args, **kwargs):
        group = Group.objects.get(name=DISPATCHERS_GROUP)
        if "remove" in request.POST:
            user = get_object_or_404(User, pk=request.POST["remove"], groups=group)
            user.groups.remove(group)
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
        messages.success(request, f"{dispatcher_name(user)} is now a dispatcher.")
        return redirect("shop_dispatchers:index")
