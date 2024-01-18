import logging

from django.conf import settings
from django.core.mail import send_mail

from paypal.standard.models import ST_PP_COMPLETED
from paypal.standard.ipn.signals import valid_ipn_received, invalid_ipn_received

from fundraising.models import RecipeBookSubmission

from .utils import signature

logger = logging.getLogger(__name__)


class PayPalError(Exception):
    ...


def send_payment_received_email(obj):
    send_mail(
        "Recipe book contribution: payment processed",
        (
            "Thank you for your payment!\n"
            f"You can view your submission at https://{settings.DOMAIN}{obj.get_absolute_url()}.\n"
            "Thank you for supporting Podencos In Need (PINS) <3."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [obj.email],
        fail_silently=False,
    )


def process_paypal(sender, **kwargs):
    ipn_obj = sender
    if ipn_obj.payment_status == ST_PP_COMPLETED:
        # WARNING !
        # Check that the receiver email is the same we previously
        # set on the `business` field. (The user could tamper with
        # that fields on the payment form before it goes to PayPal)
        if ipn_obj.receiver_email != settings.PAYPAL_EMAIL:
            # Not a valid payment
            raise(PayPalError(f"invalid receiver email {ipn_obj.receiver_email}; ipn {ipn_obj.id}"))

        obj = RecipeBookSubmission.objects.get(pk=ipn_obj.invoice)
        # ALSO: for the same reason, you need to check the amount
        # received, `custom` etc. are all what you expect or what
        # is allowed.
        if ipn_obj.mc_gross != obj.cost:
            raise(PayPalError(f"invalid amount (mc_gross) {ipn_obj.mc_gross}; ipn {ipn_obj.id}"))

        # Undertake some action depending upon `ipn_obj`.
        if ipn_obj.custom != signature(obj.reference):
            raise(PayPalError(f"invalid signature; ipn {ipn_obj.id}"))
        
        obj.paid = True
        obj.save()

        send_payment_received_email(obj)
    else:
        raise(PayPalError(f"Unexpected status: {ipn_obj.payment_status}; ipn {ipn_obj.id}"))


def process_invalid_ipn(sender, **kwargs):
    raise(PayPalError(f"Invalid IPN {sender.id}; flag_info: {sender.flag_info}"))


valid_ipn_received.connect(process_paypal)
invalid_ipn_received.connect(process_invalid_ipn)