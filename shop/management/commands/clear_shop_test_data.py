from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from salesman.core.utils import get_salesman_model
from salesman_stripe_connect.models import ConnectedAccount
from wagtail.models import ModelLogEntry

from shop.models import TEST_ORDER_PREFIX, DiscountCode

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")
OrderPayment = get_salesman_model("OrderPayment")

CONFIRMATION = "delete test data"


class Command(BaseCommand):
    help = (
        "Before launch: delete the shop's test orders (numbered TEST-..., placed "
        "in test mode; or with --all, every order), with their items, notes, "
        "payments and refunds, the discount codes they used, and their activity "
        "log entries; and all baskets. Products, stock and the shop's setup are "
        "kept (reset stock with import_shop_stock --reset-stock afterwards). Only "
        "runs in test mode (SHOP_TEST_MODE), with Stripe test keys and no live "
        "account connected, so it can't delete real orders. Shows what it would "
        "delete unless --delete is given, which asks for confirmation."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help=f"Delete (after typing '{CONFIRMATION}'); otherwise just show what would be deleted",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_orders",
            help=(
                f"Every order, not just those numbered {TEST_ORDER_PREFIX}... (e.g. test "
                "orders placed before test mode numbered them)"
            ),
        )

    def check_test_mode(self):
        """Refuse unless the shop's in test mode: then its orders are test orders"""
        if not settings.SHOP_TEST_MODE:
            raise CommandError(
                "The shop isn't in test mode (SHOP_TEST_MODE), so orders may be real: "
                "nothing has been deleted."
            )
        key = getattr(settings, "SALESMAN_STRIPE_CONNECT_SECRET_KEY", "") or ""
        if not key.startswith(("sk_test_", "rk_test_")):
            raise CommandError(
                "The site's Stripe key isn't a test key, so orders may be real: "
                "nothing has been deleted. (This is only for clearing test data "
                "before launch, while the site uses Stripe test keys.)"
            )
        if ConnectedAccount.objects.filter(livemode=True).exists():
            raise CommandError(
                "A live Stripe account is connected, so orders may be real: nothing "
                "has been deleted."
            )

    def handle(self, delete, all_orders, **kwargs):
        self.check_test_mode()
        orders = Order.objects.order_by("date_created")
        if not all_orders:
            orders = orders.filter(ref__startswith=TEST_ORDER_PREFIX)
        other_orders = Order.objects.exclude(pk__in=orders.values("pk")).count()
        used_codes = DiscountCode.objects.filter(order__in=orders)
        log_entries = ModelLogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(Order),
            object_id__in=[str(pk) for pk in orders.values_list("pk", flat=True)],
        )
        baskets = Basket.objects.all()
        paid = OrderPayment.objects.filter(order__in=orders, amount__gt=0).aggregate(
            total=Sum("amount")
        )["total"]

        count = orders.count()
        if count:
            first, last = orders.first(), orders.last()
            refs = f" ({first.ref} to {last.ref})" if count > 1 else f" ({first.ref})"
        else:
            refs = ""
        self.stdout.write(
            f"{count} test order(s){refs}, with £{paid or Decimal(0):.2f} of test payments\n"
            f"{baskets.count()} basket(s)\n"
            f"{used_codes.count()} used discount code(s)\n"
            f"{log_entries.count()} order activity log entries"
        )
        if other_orders:
            self.stdout.write(
                f"({other_orders} other order(s), not numbered {TEST_ORDER_PREFIX}..., "
                "are kept: --all to delete them too)"
            )
        if not delete:
            self.stdout.write("Nothing deleted: run with --delete to delete these.")
            return
        answer = input(f"Type '{CONFIRMATION}' to delete them: ")
        if answer.strip() != CONFIRMATION:
            raise CommandError("Not confirmed: nothing has been deleted.")
        with transaction.atomic():
            # (the codes and log entries first, while their orders exist; the
            # orders before the baskets, as deleting a basket adjusts its
            # order's stock)
            used_codes.delete()
            log_entries.delete()
            orders.delete()
            baskets.delete()
        self.stdout.write(
            "Deleted. Now reset the products' stock: "
            "python manage.py import_shop_stock <csv> --reset-stock"
        )
