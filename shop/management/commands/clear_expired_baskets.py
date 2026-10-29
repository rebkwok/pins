from django.core.management.base import BaseCommand

from salesman.core.utils import get_salesman_model

Basket = get_salesman_model("Basket")


class Command(BaseCommand):
    help = (
        "Clear items from expired baskets, returning them to stock, and delete "
        "empty baskets that haven't been updated recently. Run on a cron."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Delete empty baskets that haven't been updated for this many days (default 7)",
        )

    def handle(self, days, **kwargs):
        cleared = Basket.clear_expired()
        deleted = Basket.delete_stale(days=days)
        self.stdout.write(
            f"Cleared {cleared} expired basket(s); deleted {deleted} stale empty basket(s)"
        )
