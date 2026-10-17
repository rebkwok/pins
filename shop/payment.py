# payment.py
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.urls import reverse

from salesman.basket.models import BaseBasket
from salesman.checkout.payment import PaymentMethod
from salesman.core.utils import get_salesman_model
from salesman_stripe_connect.payment import StripeConnectPayment


Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")



def checkout_session_expiry():
    """
    How long until a checkout session expires: the basket timeout (which is at
    least 30 minutes, see settings) plus a minute, since Stripe requires
    expires_at to be at least 30 minutes after the session is created, and the
    request takes time to reach Stripe.
    """
    return timedelta(minutes=settings.BASKET_TIMEOUT_MINUTES + 1)

# Hold a basket's items a little longer than its checkout session, so that a
# payment completed just before the session expires can still be fulfilled
BASKET_PAYMENT_HOLD_MARGIN = timedelta(minutes=5)


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
        url = reverse("shop:new_order_status", args=(order.token,))
        return request.build_absolute_uri(url)


class PayByStripe(StripeConnectPayment):
    """
    Stripe Checkout payments (see salesman_stripe_connect), holding the basket's
    items while the payment is in progress.
    """

    success_template_name = "shop/stripe_success.html"
    cancel_template_name = "shop/stripe_cancel.html"

    def basket_payment(self, basket, request):
        basket.extra["name"] = request.POST.get("name")
        basket.update(request)
        return super().basket_payment(basket, request)

    def session_created(self, obj, session, request):
        if isinstance(obj, BaseBasket):
            # Starting the payment locks the basket, and holds its items until
            # the session expires
            expires_at = datetime.fromtimestamp(session.expires_at, UTC)
            obj.start_payment(
                session.id,
                session.url,
                hold_until=expires_at + BASKET_PAYMENT_HOLD_MARGIN,
            )

    def get_session_data(self, obj, request):
        session_data = super().get_session_data(obj, request)
        session_data["metadata"] = {"shipping_method": obj.shipping_method}
        return session_data

    def get_session_expiry(self, obj):
        return checkout_session_expiry()

    @classmethod
    def basket_payment_expired(cls, basket):
        # Return the basket's items to stock
        basket.clear()
        basket.timeout = None

    @classmethod
    def basket_payment_cancelled(cls, basket):
        # The basket keeps its items, with a new timeout
        basket.reset_timeout()

    @classmethod
    def get_request_basket(cls, request):
        return Basket.get_existing(request)

    @classmethod
    def get_view_context(cls, request):
        return {"hide_basket": True}
