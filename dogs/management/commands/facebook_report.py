from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.core.mail import send_mail

from dogs.models import FacebookAlbumTracker


class Command(BaseCommand):
    help = 'report Facebook changes'

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            action="store_true",
            help="Send to support email",
        )
        return super().add_arguments(parser)

    def handle(self, email, **kwargs):
        tracker = FacebookAlbumTracker()
        new_data = tracker.fetch_all()
        changes = tracker.report_changes(new_data)

        mail_content = [f"Facebook album changes as of {datetime.utcnow()}"]
        for change, changed_data in changes.items():
            if changed_data:
                mail_content.append("\n==============================================")
                mail_content.append(change)
                mail_content.append("==============================================")
            for key, val in changed_data.items():
                if change != "custom_albums":
                    mail_content.append(f"{key}: {val}")
                else:
                    mail_content.append(f"{key}: {val.get('link', '')}")
        
        mail_content = "\n".join(mail_content)
        self.stdout.write(mail_content)
        if email:
            send_mail(
                subject="Facebook album report",
                message=mail_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.SUPPORT_EMAIL]
            )


