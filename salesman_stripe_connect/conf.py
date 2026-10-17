from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class AppSettings:
    """
    Settings, read from Django settings when they're used (so tests can
    override them).
    """

    @property
    def SALESMAN_STRIPE_CONNECT_SECRET_KEY(self):
        """The platform's Stripe secret key"""
        return self._required("SALESMAN_STRIPE_CONNECT_SECRET_KEY")

    @property
    def SALESMAN_STRIPE_CONNECT_WEBHOOK_SECRET(self):
        """Signing secret of the webhook endpoint for connected accounts' events"""
        return self._required("SALESMAN_STRIPE_CONNECT_WEBHOOK_SECRET")

    @property
    def SALESMAN_STRIPE_CONNECT_ACCOUNT(self):
        """Id of the connected account that payments are made to (acct_...)"""
        return self._required("SALESMAN_STRIPE_CONNECT_ACCOUNT")

    @property
    def SALESMAN_STRIPE_CONNECT_CURRENCY(self):
        """
        ISO currency code for payments. Only currencies with 2 decimal places
        (e.g. gbp, eur, usd) are supported.
        """
        return getattr(settings, "SALESMAN_STRIPE_CONNECT_CURRENCY", "gbp").lower()

    @property
    def SALESMAN_STRIPE_CONNECT_PAYMENT_LABEL(self):
        """Payment method label shown at checkout"""
        return getattr(settings, "SALESMAN_STRIPE_CONNECT_PAYMENT_LABEL", "Pay with Stripe")

    @property
    def SALESMAN_STRIPE_CONNECT_PAID_STATUS(self):
        """Status of orders created when a checkout session is paid"""
        return getattr(settings, "SALESMAN_STRIPE_CONNECT_PAID_STATUS", "PROCESSING")

    def _required(self, name):
        value = getattr(settings, name, None)
        if not value:
            raise ImproperlyConfigured(f"The {name} setting is required")
        return value


app_settings = AppSettings()
