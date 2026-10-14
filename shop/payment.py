# payment.py
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from salesman.checkout.payment import PaymentMethod
from salesman_stripe.payment import StripePayment
from salesman.core.utils import get_salesman_model
from salesman_stripe.conf import app_settings as stripe_settings

import stripe
stripe.api_version = "2026-09-30.endive"


Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")
OrderNote = get_salesman_model("OrderNote")
OrderPayment = get_salesman_model("OrderPayment")

logger = logging.getLogger(__name__)


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
    def handle_webhook_session_completed(cls, request, session):
        """
        Fulfil the order after a successful checkout session.

        Replaces salesman_stripe's handler so that:
        - duplicate events (Stripe can send an event more than once) don't
          create a second payment
        - unrecoverable problems (missing basket or order) are logged and return
          200, so Stripe doesn't keep retrying
        - a payment for an empty basket (e.g. items expired) or a payment amount
          that doesn't match the order total is recorded on the order, so the
          shop can resolve it
        """
        kind, id = cls.parse_reference(session.client_reference_id)
        if kind is None:
            logger.error("Invalid Stripe session reference: %s", session.id)
            return HttpResponse("Invalid session reference")

        with transaction.atomic():
            # Lock the basket so that concurrent deliveries of the same event
            # are processed one at a time
            basket = (
                Basket.objects.select_for_update().filter(id=id).first()
                if kind == "basket"
                else None
            )
            if OrderPayment.objects.filter(
                transaction_id=session.payment_intent
            ).exists():
                logger.info(
                    "Stripe payment %s already processed", session.payment_intent
                )
                return HttpResponse("Order already fulfilled")

            if kind == "basket":
                if basket is None:
                    logger.error(
                        "Stripe payment %s received for missing basket %s",
                        session.payment_intent,
                        id,
                    )
                    return HttpResponse("Missing basket")
                basket_was_empty = not basket.items.exists()
                order = Order.objects.create_from_basket(
                    basket, request, status=stripe_settings.SALESMAN_STRIPE_PAID_STATUS
                )
                basket.delete()
                if basket_was_empty:
                    cls._flag_order(
                        order,
                        f"Payment {session.payment_intent} was received but the "
                        "basket was empty (items may have expired). Check and refund "
                        "if necessary.",
                    )
            else:
                order = Order.objects.filter(id=id).first()
                if order is None:
                    logger.error(
                        "Stripe payment %s received for missing order %s",
                        session.payment_intent,
                        id,
                    )
                    return HttpResponse("Missing order")

            amount = Decimal(session.amount_total) / 100
            if amount != order.total:
                cls._flag_order(
                    order,
                    f"Payment {session.payment_intent} of £{amount:.2f} doesn't "
                    f"match the order total of £{order.total:.2f}.",
                )
            order.pay(
                amount=amount,
                transaction_id=session.payment_intent,
                payment_method=cls.identifier,
            )

        logger.info("Order fulfilled: %s", order.ref)
        return HttpResponse("Order fulfilled")

    @classmethod
    def _flag_order(cls, order, message):
        """Add a (non-public) note to the order, and log the problem"""
        OrderNote.objects.create(order=order, message=message, public=False)
        logger.error("Order %s: %s", order.ref, message)

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
