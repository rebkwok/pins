from django.conf import settings
from django.core.management.base import BaseCommand
from wagtail.admin.mail import send_mail

from django.core.management.base import BaseCommand

from fundraising.models import Auction


class Command(BaseCommand):
    help = 'Send emails for unsold auction items'

    def add_arguments(self, parser):
        parser.add_argument(
            "auction_id",
            type=int,
            help="Auction page ID",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
        )
        return super().add_arguments(parser)

    def handle(self, auction_id, dry_run, **kwargs):
        auction = Auction.objects.get(id=auction_id)
        assert auction.is_closed()

        auction_items = auction.get_children().specific()
        unsold_items = [it for it in auction_items if not it.active_bids]
        items_by_donor = {}
        for unsold_item in unsold_items:
            items_by_donor.setdefault((unsold_item.donor, unsold_item.donor_email), []).append(unsold_item.title)

        for (donor, donor_email), donor_items in items_by_donor.items():
            items_str = "\n".join([f"- {donor_item}" for donor_item in donor_items])
            item_plural = "s" if len(donor_items) > 1 else ""
            subject=f"Your items in the PINS auction ({auction.title})"
            message=message_body(donor, item_plural, items_str)
            if dry_run:
                print(
                    f"""
                    Would send email to {donor_email}:
                    Subject: {subject}
                    Body: 
                    {message}
                    """.strip()
                )
            else:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[donor_email],
                    reply_to=[settings.DEFAULT_ADMIN_EMAIL]
                )

                
def message_body(donor, item_plural, items_str):
    return f"""
Dear {donor.split()[0]},

Thank you for your generous donation to our auction. Unfortunately we weren't able to sell your item{item_plural} this time:
{items_str}

We welcome any other items you have in future.  Please send a message to the PINS facebook auction page
and we will be in touch.

Thank you again for your support for the dogs,
PINS Auctions
"""