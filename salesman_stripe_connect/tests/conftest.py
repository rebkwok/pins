"""
The app's tests use the project's salesman models (configured in settings) and
the basket and order fixtures from the project's conftest.
"""
from decimal import Decimal

import pytest
from django.conf import settings
from django.core import mail
from salesman.core.utils import get_salesman_model

from ..payment import StripeConnectPayment

Order = get_salesman_model("Order")


@pytest.fixture
def account():
    return settings.SALESMAN_STRIPE_CONNECT_ACCOUNT


@pytest.fixture
def payment():
    return StripeConnectPayment()


@pytest.fixture
def checkout_basket(basket):
    # The fields added by the checkout when the basket goes to payment
    basket.extra.update(
        {
            "email": "test@test.com",
            "shipping_address": "-",
            "billing_address": "-",
            "payment_method": "stripe",
        }
    )
    basket.save()
    yield basket


@pytest.fixture
def paying_basket(checkout_basket):
    checkout_basket.start_payment("test-session", "https://stripe-session-url")
    yield checkout_basket


@pytest.fixture
def paid_order(order):
    # order total is £20
    order.status = Order.Status.PROCESSING
    order.email = "customer@test.com"
    order.save()
    order.pay(amount=Decimal("20.00"), transaction_id="pi_1", payment_method="stripe")
    mail.outbox.clear()
    yield order
