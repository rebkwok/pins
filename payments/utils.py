from hashlib import sha512

from django.conf import settings


def signature(reference):
    return sha512((str(reference) + settings.PAYPAL_CUSTOM_KEY).encode("utf-8")).hexdigest()