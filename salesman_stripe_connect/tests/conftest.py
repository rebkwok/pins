"""
The app's tests use the project's salesman models (configured in settings) and
the basket and order fixtures from the project's conftest.
"""
from decimal import Decimal

import pytest
from django.core import mail
from salesman.core.utils import get_salesman_model

from ..models import ConnectedAccount
from ..payment import StripeConnectPayment
from .utils import ACCOUNT

Order = get_salesman_model("Order")


@pytest.fixture(autouse=True)
def connected_account(request):
    """
    Tests that use the database have a connected Stripe account (ACCOUNT)
    """
    marker = request.node.get_closest_marker("django_db")
    if marker is None:
        yield None
        return
    transaction = marker.kwargs.get("transaction", False)
    request.getfixturevalue("transactional_db" if transaction else "db")
    account = ConnectedAccount(account_id=ACCOUNT, livemode=False)
    account.save()
    yield account


@pytest.fixture
def account():
    return ACCOUNT


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
