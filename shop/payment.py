# payment.py
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from salesman.basket.models import BaseBasket
from salesman.checkout.payment import PaymentError, PaymentMethod
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
        url = reverse("salesman-order-last") + f"?token={order.token}"
        return request.build_absolute_uri(url)


class PayByStripe(StripePayment):

    def basket_payment(self, basket, request):
        if basket.payment_in_progress:
            raise PaymentError("A payment is already in progress for this basket")
        basket.extra["name"] = request.POST.get("name")
        basket.update(request)
        # Creating the Stripe session starts the payment, which locks the basket
        # and holds its items until the session expires (see get_stripe_session)
        return super().basket_payment(basket, request)

    def get_stripe_session(self, obj, request):
        session = super().get_stripe_session(obj, request)
        if isinstance(obj, BaseBasket):
            expires_at = datetime.fromtimestamp(session.expires_at, UTC)
            obj.start_payment(
                session.id,
                session.url,
                hold_until=expires_at + BASKET_PAYMENT_HOLD_MARGIN,
            )
        return session

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
        session_data["expires_at"] = int(
            (timezone.now() + checkout_session_expiry()).timestamp()
        )
        return session_data

    @classmethod
    def handle_webhook_event(cls, request, event):
        if event.type == "checkout.session.expired":
            _, message = cls.expire_basket_payment(event.data.object)
            return HttpResponse(message)
        return super().handle_webhook_event(request, event)

    @classmethod
    def handle_webhook_session_completed(cls, request, session):
        """
        Replaces salesman_stripe's handler with fulfil_session, which is also
        called from the success view.
        Unrecoverable problems (missing basket or order) are logged and return
        200, so Stripe doesn't keep retrying.
        """
        _, message = cls.fulfil_session(request, session)
        return HttpResponse(message)

    @classmethod
    def fulfil_session(cls, request, session):
        """
        Create and pay the order for a completed checkout session.

        Called from both the webhook and the success view, so it's safe to call
        more than once, including concurrently: the order records the Stripe
        session id, and whichever call comes first creates the order and
        payment; later calls return the existing order.

        A payment for an empty basket (e.g. items expired) or a payment amount
        that doesn't match the order total is recorded on the order, so the
        shop can resolve it.

        Returns (order, message); order is None if it couldn't be fulfilled.
        """
        kind, id = cls.parse_reference(session.client_reference_id)
        if kind is None:
            logger.error("Invalid Stripe session reference: %s", session.id)
            return None, "Invalid session reference"

        with transaction.atomic():
            # Lock the basket or order so that concurrent calls for the same
            # session are processed one at a time
            if kind == "basket":
                basket = Basket.objects.select_for_update().filter(id=id).first()
            else:
                order = Order.objects.select_for_update().filter(id=id).first()

            existing_order = Order.objects.filter(
                _extra__stripe_session_id=session.id
            ).first()
            if existing_order is None:
                payment = (
                    OrderPayment.objects.filter(transaction_id=session.payment_intent)
                    .select_related("order")
                    .first()
                )
                existing_order = payment.order if payment else None
            if existing_order is not None:
                logger.info("Stripe session %s already fulfilled", session.id)
                return existing_order, "Order already fulfilled"

            if kind == "basket":
                if basket is None:
                    logger.error(
                        "Stripe payment %s received for missing basket %s",
                        session.payment_intent,
                        id,
                    )
                    return None, "Missing basket"
                basket_was_empty = not basket.items.exists()
                # basket.extra is copied to order.extra
                basket.extra.pop(Basket.STRIPE_SESSION_KEY, None)
                basket.extra["stripe_session_id"] = session.id
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
                if order is None:
                    logger.error(
                        "Stripe payment %s received for missing order %s",
                        session.payment_intent,
                        id,
                    )
                    return None, "Missing order"
                order.extra["stripe_session_id"] = session.id
                order.save()

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
        return order, "Order fulfilled"

    @classmethod
    def expire_basket_payment(cls, session):
        """
        The checkout session has expired: if its basket is still waiting for it,
        clear the basket (returning its items to stock) and unlock it.
        Returns (basket or None, message).
        """
        kind, id = cls.parse_reference(session.client_reference_id)
        if kind != "basket":
            return None, "Event ignored"
        with transaction.atomic():
            basket = Basket.objects.select_for_update().filter(id=id).first()
            if basket is None or basket.stripe_session_id != session.id:
                # Basket has been fulfilled, cleared, or its payment cancelled
                return None, "Event ignored"
            basket.clear()
            basket.timeout = None
            basket.end_payment()
        logger.info("Stripe session %s expired; basket %s cleared", session.id, id)
        return basket, "Basket cleared"

    @classmethod
    def cancel_basket_payment(cls, basket):
        """
        Expire the basket's checkout session (e.g. the customer wants to change
        their basket) and unlock the basket, keeping its items.
        Returns False if the session has already completed, so can't be cancelled.
        Raises StripeError if the session can't be expired or retrieved.
        """
        with transaction.atomic():
            # Lock the basket, so the expired webhook waits until it's unlocked
            basket = Basket.objects.select_for_update().get(id=basket.id)
            if not basket.payment_in_progress:
                return True
            try:
                stripe.checkout.Session.expire(basket.stripe_session_id)
            except stripe.InvalidRequestError:
                # The session isn't open; it has either expired or completed
                session = stripe.checkout.Session.retrieve(basket.stripe_session_id)
                if session.status == "complete":
                    return False
            basket.end_payment()
            basket.reset_timeout()
        return True

    @classmethod
    def check_basket_payment(cls, request, basket):
        """
        Check the status of the basket's checkout session with Stripe (e.g. when
        the customer returns to their basket) rather than waiting for a webhook.
        Fulfils the order if the session has been paid, or clears the basket if it
        has expired.
        Returns the order if the session has been paid, otherwise None.
        """
        try:
            session = stripe.checkout.Session.retrieve(basket.stripe_session_id)
        except stripe.StripeError:
            logger.exception(
                "Error retrieving Stripe session %s", basket.stripe_session_id
            )
            return None
        if session.status == "complete" and session.payment_status == "paid":
            order, _ = cls.fulfil_session(request, session)
            return order
        if session.status == "expired":
            cls.expire_basket_payment(session)
        return None

    @classmethod
    def _flag_order(cls, order, message):
        """Add a (non-public) note to the order, and log the problem"""
        OrderNote.objects.create(order=order, message=message, public=False)
        logger.error("Order %s: %s", order.ref, message)

    @classmethod
    def cancel_view(cls, request):
        """
        Handle cancelled payment on Stripe; unlock the basket so the customer
        can change it.
        """
        basket = Basket.get_existing(request)
        if basket is not None and basket.payment_in_progress:
            try:
                cls.cancel_basket_payment(basket)
            except stripe.StripeError:
                logger.exception(
                    "Error cancelling Stripe session %s", basket.stripe_session_id
                )
        return render(request, "shop/stripe_cancel.html")

    @classmethod
    def success_view(cls, request):
        """
        Handle successful payment on Stripe.
        Fulfil the order here as well as in the webhook, so the customer sees
        their order (and an empty basket) without waiting for the webhook.
        If anything goes wrong, the webhook will still fulfil the order.
        """
        context = {"hide_basket": True}
        checkout_session_id = request.GET.get("session_id")
        try:
            session = (
                stripe.checkout.Session.retrieve(checkout_session_id)
                if checkout_session_id
                else None
            )
        except stripe.StripeError:
            logger.exception("Error retrieving Stripe session %s", checkout_session_id)
            session = None

        if session is not None:
            context["email"] = session.customer_details.email
            context["total"] = Decimal(session.amount_total) / 100
            if session.payment_status == "paid":
                try:
                    context["order"], _ = cls.fulfil_session(request, session)
                except Exception:
                    logger.exception(
                        "Error fulfilling Stripe session %s from success view",
                        session.id,
                    )
        return render(request, "shop/stripe_success.html", context)


@csrf_exempt
def stripe_webhook_view(request):
    return PayByStripe.webhook_view(request)
