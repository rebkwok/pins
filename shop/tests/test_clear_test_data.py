"""
clear_shop_test_data: deleting the shop's test orders before launch, only in
test mode (and Stripe test mode)
"""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command
from model_bakery import baker
from salesman.core.utils import get_salesman_model
from salesman_stripe_connect.models import ConnectedAccount
from wagtail.models import ModelLogEntry

from .. import activity
from ..models import DiscountCode, ProductVariant
from .test_shipping import dispatcher, make_dispatcher, make_order, shop_variants  # noqa: F401

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")
OrderItem = get_salesman_model("OrderItem")
OrderPayment = get_salesman_model("OrderPayment")


@pytest.fixture(autouse=True)
def test_mode(settings):
    settings.SHOP_TEST_MODE = True
    settings.SALESMAN_STRIPE_CONNECT_SECRET_KEY = "sk_test_123"


@pytest.fixture
def test_data(shop_variants, settings):
    mug, card, raffle = shop_variants
    # an order placed before test mode numbered orders (TEST-...)
    settings.SHOP_TEST_MODE = False
    earlier = make_order([raffle])
    activity.log_order(earlier, activity.ORDER_NOTE, message="Earlier")
    earlier_code = baker.make(DiscountCode, code="EARLIER", amount=5, order=earlier)
    settings.SHOP_TEST_MODE = True
    used = baker.make(DiscountCode, code="USED", amount=5)
    unused = baker.make(DiscountCode, code="UNUSED", amount=5)
    first = make_order([mug])
    first.pay(amount=first.total, transaction_id="pi_1", payment_method="stripe")
    second = make_order([card])
    second.pay(amount=second.total, transaction_id="pi_2", payment_method="stripe")
    second.pay(amount=-2, transaction_id="re_1", payment_method="stripe")
    used.order = second
    used.save()
    activity.log_order(second, activity.ORDER_NOTE, message="Test")
    basket = baker.make(Basket)
    basket.add(mug)
    return {
        "orders": [first, second],
        "earlier": earlier,
        "used": used,
        "unused": unused,
        "earlier_code": earlier_code,
    }


def run(*args, answer=None):
    out = StringIO()
    with patch("builtins.input", return_value=answer) as prompt:
        call_command("clear_shop_test_data", *args, stdout=out)
    return out.getvalue(), prompt


def log_count(*orders):
    return ModelLogEntry.objects.filter(
        content_type__model="order", object_id__in=[str(order.pk) for order in orders]
    ).count()


def test_dry_run(test_data):
    # shows what would be deleted (the TEST- orders), and deletes nothing
    first, second = test_data["orders"]
    assert first.ref.startswith("TEST-") and second.ref.startswith("TEST-")
    assert not test_data["earlier"].ref.startswith("TEST-")
    output, prompt = run()
    total = first.total + second.total
    assert output == (
        f"2 test order(s) ({first.ref} to {second.ref}), with £{total:.2f} of test payments\n"
        f"{Basket.objects.count()} basket(s)\n"
        "1 used discount code(s)\n"
        f"{log_count(first, second)} order activity log entries\n"
        "(1 other order(s), not numbered TEST-..., are kept: --all to delete them too)\n"
        "Nothing deleted: run with --delete to delete these.\n"
    )
    prompt.assert_not_called()
    assert Order.objects.count() == 3
    assert Basket.objects.exists()


def test_delete(test_data, shop_variants):
    # the TEST- orders, with their items, payments, codes and log entries; all
    # baskets. The earlier order (and its code and log entries) is kept, as are
    # unused codes and products.
    first, second = test_data["orders"]
    earlier = test_data["earlier"]
    earlier_logs = log_count(earlier)
    output, prompt = run("--delete", answer="delete test data")
    prompt.assert_called_once_with("Type 'delete test data' to delete them: ")
    assert "Deleted. Now reset the products' stock" in output
    assert list(Order.objects.all()) == [earlier]
    assert not OrderItem.objects.filter(order__in=[first.pk, second.pk]).exists()
    assert not OrderPayment.objects.filter(order__in=[first.pk, second.pk]).exists()
    assert not Basket.objects.exists()
    assert log_count(first, second) == 0
    assert log_count(earlier) == earlier_logs
    assert set(DiscountCode.objects.values_list("code", flat=True)) == {"UNUSED", "EARLIER"}
    assert ProductVariant.objects.count() == len(shop_variants)


def test_delete_all(test_data):
    # --all: every order, e.g. test orders from before they were numbered TEST-
    output, _ = run("--all")
    assert output.startswith("3 test order(s)")
    assert "other order(s)" not in output
    run("--all", "--delete", answer="delete test data")
    assert not Order.objects.exists()
    assert set(DiscountCode.objects.values_list("code", flat=True)) == {"UNUSED"}
    assert not ModelLogEntry.objects.filter(content_type__model="order").exists()


@pytest.mark.parametrize("answer", ["", "yes", "delete"])
def test_delete_not_confirmed(test_data, answer):
    with pytest.raises(CommandError, match="Not confirmed: nothing has been deleted."):
        run("--delete", answer=answer)
    assert Order.objects.count() == 3


def test_refused_outside_test_mode(test_data, settings):
    # e.g. after launch: it never runs, even to show what it would delete
    settings.SHOP_TEST_MODE = False
    for args in [(), ("--delete",), ("--all", "--delete")]:
        with pytest.raises(CommandError, match=r"The shop isn't in test mode \(SHOP_TEST_MODE\)"):
            run(*args, answer="delete test data")
    assert Order.objects.count() == 3


@pytest.mark.parametrize("key", ["sk_live_123", "rk_live_123", "", None])
def test_refused_with_live_key(test_data, settings, key):
    settings.SALESMAN_STRIPE_CONNECT_SECRET_KEY = key
    for args in [(), ("--delete",)]:
        with pytest.raises(CommandError, match="The site's Stripe key isn't a test key"):
            run(*args, answer="delete test data")
    assert Order.objects.count() == 3


def test_refused_with_live_account(test_data):
    ConnectedAccount.objects.update(livemode=True)
    with pytest.raises(CommandError, match="A live Stripe account is connected"):
        run("--delete", answer="delete test data")
    assert Order.objects.count() == 3


def test_nothing_to_delete():
    output, _ = run()
    assert output.startswith("0 test order(s), with £0.00 of test payments\n")


def test_one_order(shop_variants):
    mug, card, raffle = shop_variants
    order = make_order([mug])
    assert run()[0].startswith(f"1 test order(s) ({order.ref}), with £0.00 of test payments\n")
