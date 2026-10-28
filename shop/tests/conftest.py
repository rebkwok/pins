import pytest

from django.core.cache import cache

from salesman_stripe_connect.models import ConnectedAccount

from .factories import STRIPE_ACCOUNT


@pytest.fixture(autouse=True)
def clear_cache():
    # The basket middleware uses the cache to throttle clearing expired baskets;
    # clear it so tests don't affect each other
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def connected_account(request):
    """
    Tests that use the database have a connected Stripe account (STRIPE_ACCOUNT)
    """
    marker = request.node.get_closest_marker("django_db")
    if marker is None:
        yield None
        return
    transaction = marker.kwargs.get("transaction", False)
    request.getfixturevalue("transactional_db" if transaction else "db")
    account = ConnectedAccount(account_id=STRIPE_ACCOUNT, livemode=False)
    account.save()
    yield account


STRIPE_CUSTOMERS_URL = "https://api.stripe.com/v1/customers"


@pytest.fixture(autouse=True)
def stripe_customers(requests_mock):
    """
    Stripe's API is faked in every test (requests_mock: an unexpected request
    fails), with a customer (cus_test) for every email, as checkout sessions
    look the customer up (salesman_stripe_connect's get_customer)
    """
    yield requests_mock.get(
        STRIPE_CUSTOMERS_URL,
        json={"object": "list", "data": [{"id": "cus_test", "object": "customer"}], "has_more": False},
    )
