from hashlib import sha512

from django.conf import settings
from django.urls import reverse

from paypal.standard.forms import PayPalPaymentsForm


def signature(reference):
    return sha512((str(reference) + settings.PAYPAL_CUSTOM_KEY).encode("utf-8")).hexdigest()


def get_paypal_form(request, amount, item_name, reference):
    request.session["paypal_item_reference"] = reference
    if settings.PAYPAL_TEST and settings.PAYPAL_TEST_CALLBACK_DOMAIN:
        paypal_urls = {
            "notify_url": f"{settings.PAYPAL_TEST_CALLBACK_DOMAIN}{reverse('paypal-ipn')}",
            "return": f"{settings.PAYPAL_TEST_CALLBACK_DOMAIN}{reverse('payments:paypal_return')}",
            "cancel_return": f"{settings.PAYPAL_TEST_CALLBACK_DOMAIN}{reverse('payments:paypal_cancel')}",
        }
    else:
        paypal_urls = {
            "notify_url": request.build_absolute_uri(reverse('paypal-ipn')),
            "return": request.build_absolute_uri(reverse('payments:paypal_return')),
            "cancel_return": request.build_absolute_uri(reverse('payments:paypal_cancel')),
        }

    paypal_dict = {
        "business": settings.PAYPAL_EMAIL,
        "amount": amount,
        "item_name": item_name,
        "invoice": reference,
        "currency_code": "GBP",
        "custom": signature(reference),
        **paypal_urls
    }
    return PayPalPaymentsForm(initial=paypal_dict)