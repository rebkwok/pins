import logging

from django.conf import settings
from django.core.mail import send_mail

from paypal.standard.models import ST_PP_COMPLETED
from paypal.standard.ipn.signals import valid_ipn_received, invalid_ipn_received

from fundraising.models import RecipeBookSubmission
from home.models import OrderFormSubmission

from .utils import signature

logger = logging.getLogger(__name__)


def send_payment_received_email(obj, subject, payment_item):
    send_mail(
        f"{subject}: payment processed",
        (
            "Thank you for your payment!\n"
            f"You can view your {payment_item} at https://{settings.DOMAIN}{obj.get_absolute_url()}.\n"
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
            logger.error(
                "Invalid receiver email %s; ipn %s", ipn_obj.receiver_email, ipn_obj.id
            )
            return

        try:
            obj = RecipeBookSubmission.objects.get(pk=ipn_obj.invoice)
            subject = "Recipe book contribution"
            payment_item = "submission"
        except RecipeBookSubmission.DoesNotExist:
            obj = OrderFormSubmission.objects.get(reference=ipn_obj.invoice)
            subject = f"{obj.page.orderformpage.subject_title} order"
            payment_item = "order"
        # ALSO: for the same reason, you need to check the amount
        # received, `custom` etc. are all what you expect or what
        # is allowed.
        if ipn_obj.mc_gross != obj.cost:
            logger.error(
                "Invalid amount (mc_gross) %s; ipn %s", ipn_obj.mc_gross, ipn_obj.id
            )
            return

        # Check the signature in the custom field
        if ipn_obj.custom != signature(obj.reference):
            logger.error("Invalid signature; ipn %s", ipn_obj.id)
            return 
        
        if ipn_obj.flag_info:
            logger.warn("Payal ipn %s has completed status and flag info '%s'", ipn_obj.id, ipn_obj.flag_status)

        obj.paid = True
        obj.save()

        send_payment_received_email(obj, subject, payment_item)
    else:
        logger.error(
            "Unexpected status %s; ipn %s", ipn_obj.payment_status, ipn_obj.id
        )
        return


def process_invalid_ipn(sender, **kwargs):
    logger.error(
            "Invalid IPN %s; flag_info %s", sender.id, sender.flag_info
        )

valid_ipn_received.connect(process_paypal)
invalid_ipn_received.connect(process_invalid_ipn)