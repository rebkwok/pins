import csv
from django.conf import settings
from django.core.management.base import BaseCommand
from wagtail.admin.mail import send_mail
from wagtail.images.models import Image
from wagtail.models.media import Collection

from pathlib import Path

from django.core.management.base import BaseCommand

from fundraising.models import Auction, AuctionCategory, AuctionItem, AuctionItemPhoto


class Command(BaseCommand):
    help = 'Upload auction items'

    def add_arguments(self, parser):
        parser.add_argument(
            "auction_id",
            type=int,
            help="Auction page ID",
        )
        parser.add_argument(
            "collection_id",
            type=int,
            help="Collection ID",
        )
        parser.add_argument(
            "csv_path",
            type=Path,
            help="Path to csv file with auction items",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
        )
        return super().add_arguments(parser)

    def handle(self, auction_id, collection_id, csv_path, dry_run, **kwargs):
        auction = Auction.objects.get(id=auction_id)
        collection_images = Image.objects.filter(collection_id=collection_id)

        with csv_path.open() as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                if row["Title"]:
                    if row["Uploaded"] != "N":
                        self.stdout.write(f"Skipped auction item: {row['Title']}")
                        continue
                    category, _ = AuctionCategory.objects.get_or_create(name__iexact=row["Category"].strip())
                    postage = row["Postage £"]
                    if postage:
                        postage = postage.lstrip("£").strip()
                    starting_bid=row["Starting bid £"].lstrip("£").strip()

                    auction_item = AuctionItem(
                        category=category,
                        title=row["Title"].strip(),
                        description=row["Description"].strip(),
                        donor=row["Donated by"].strip(),
                        donor_email=row["Email"].strip(),
                        starting_bid=starting_bid,
                        postage=postage if postage else 0,
                        live=False
                    )
                    auction.add_child(instance=auction_item)

                    images = [img.strip().split(".")[0] for img in row["Images"].strip().split(",") if img]
                    for image_name in images:
                        self.stdout.write(f"Adding image {image_name}")
                        collection_image = collection_images.get(title__iexact=image_name)
                        AuctionItemPhoto.objects.create(page=auction_item, image=collection_image)
                    self.stdout.write(f"Created auction item: {auction_item.title}")
