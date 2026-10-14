# payment.py
from django.conf import settings
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from salesman.checkout.payment import PaymentMethod
from salesman_stripe.payment import StripePayment
from salesman.core.utils import get_salesman_model

import stripe
stripe.api_version = "2026-09-30.endive"


Order = get_salesman_model("Order")


PAYMENT_METHOD_DESCRIPTIONS = {
    "pay-in-advance": """
        Offline payment; your order will be placed on hold until
        payment has been received
    """,
    "stripe": "Pay with stripe",
}

PAYMENT_METHOD_BUTTON_TEXT = {
    "pay-in-advance": "Submit Order",
    "stripe": "Pay Now",
}


class PayInAdvance(PaymentMethod):
    """
    Payment method that requires advance payment via bank account.
    """

    identifier = "pay-in-advance"
    label = "Pay in advance"

    def basket_payment(self, basket, request):
        """
        Create a new order and mark it on-hold. Reserve items from stock and await
        manual payment from customer via back account. When paid order status should be
        changed to `PROCESSING`, `SHIPPED` or `COMPLETED` and a new payment should be
        added to order.
        """
        basket.extra["name"] = request.POST.get("name")
        order = Order.objects.create_from_basket(basket, request, status="HOLD")
        basket.delete()
        url = reverse("salesman-order-last") + f"?token={order.token}"
        return request.build_absolute_uri(url)


class PayByStripe(StripePayment):

    def basket_payment(self, basket, request):
        basket.extra["name"] = request.POST.get("name")
        # update will also reset timeout, so we now have 15 mins to process stripe
        basket.update(request)
        return super().basket_payment(basket, request)

    def get_stripe_session_data(
        self,
        obj,  # BasketOrOrder,
        request,
    ):
        """
        Returns Stripe session data to be sent during checkout create.

        See available data to be set in Stripe:
        https://stripe.com/docs/api/checkout/sessions/create
        """
        session_data = super().get_stripe_session_data(obj, request)
        connected_stripe_account_id = settings.STRIPE_CONNECTED_ACCOUNT
        # add in the connect client info
        session_data["payment_intent_data"] = {
            "on_behalf_of": connected_stripe_account_id,
            "transfer_data": {
                "destination": connected_stripe_account_id,
            },
        }
        # add in the shipping method
        session_data["metadata"] = {"shipping_method": obj.shipping_method}
        # return the session id
        session_data["success_url"] += "?session_id={CHECKOUT_SESSION_ID}"
        return session_data

    @classmethod
    def cancel_view(cls, request):
        """
        Handle cancelled payment on Stripe.
        """
        return render(request, "shop/stripe_cancel.html")

    @classmethod
    def success_view(cls, request):
        """
        Handle successfull payment on Stripe.
        """
        checkout_session_id = request.GET.get("session_id")
        session = stripe.checkout.Session.retrieve(checkout_session_id)
        customer = stripe.Customer.retrieve(session.customer)
        context = {"email": customer.email, "total": session.amount_total / 100}
        return render(request, "shop/stripe_success.html", context)


@csrf_exempt
def stripe_webhook_view(request):
    return PayByStripe.webhook_view(request)
