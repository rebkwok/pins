from wagtail.admin import messages
from django.shortcuts import redirect
from salesman.admin.wagtail.views import OrderRefundView as SalesmanOrderRefundView

from .payment import PayByStripe


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
