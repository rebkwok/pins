import csv
from django.conf import settings
from django.core.management.base import BaseCommand
from wagtail.admin.mail import send_mail

from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Send despatch emails from csv of file exported from click & drop report'

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            type=Path,
            help="Path to csv file downloaded from click & drop report",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
        )
        return super().add_arguments(parser)

    def handle(self, csv_path, dry_run, **kwargs):
        with csv_path.open() as infile:
            reader = csv.DictReader(infile)
            for i, row in enumerate(reader):
                email=row['Notification email address']
                subject="Your PINS recipe book has been dispatched!"
                message="\n".join(
                        [
                        "Hello,",
                        f"Your PINS recipe book order (ref {row['Channel reference']}) has been dispatched by Royal Mail Tracked 48.",
                        f"Your tracking number is {row['Tracking number']}; track your delivery at https://www.royalmail.com/track-your-item#/tracking-results/{row['Tracking number']}.",
                        "We hope you enjoy the book as much as we've enjoyed making it!",
                        "Thank you again for your support.",
                        "The PINS team.",
                        ]
                )
                if dry_run:
                    print(
                        f"""
                        Would send email to {email}:
                        Subject: {subject}
                        Body: 
                        {message}
                        """
                    )
                else:
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        reply_to=[settings.DEFAULT_ADMIN_EMAIL]
                    )

