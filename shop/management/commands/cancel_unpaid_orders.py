from datetime import timedelta

from django.core.management.base import BaseCommand

from shop.payment import PayByStripe


class Command(BaseCommand):
    help = (
        "Cancel orders still awaiting a payment that completes later (e.g. a bank "
        "transfer the customer never made, which Stripe doesn't fail) after some "
        "days: their stock and discount codes are released, and the customer and "
        "shop emailed. Each payment is checked with Stripe first (see "
        "salesman_stripe_connect's expire_pending_orders). Run on a cron, e.g. "
        "daily."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Cancel orders awaiting payment for longer than this (default 7)",
        )

    def handle(self, days, **kwargs):
        results = PayByStripe.expire_pending_orders(timedelta(days=days))
        for order, outcome in results:
            self.stdout.write(f"Order {order.ref}: {outcome}")
        self.stdout.write(f"Checked {len(results)} unpaid order(s)")
