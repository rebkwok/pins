from datetime import datetime, UTC
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import send_mail

from dogs.models import FacebookAlbumTracker


class Command(BaseCommand):
    help = 'Update facebook data and report changes'

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            action="store_true",
            help="Send to support email",
        )
        return super().add_arguments(parser)

    def handle(self, email, **kwargs):
        tracker = FacebookAlbumTracker()
        changes = tracker.update_all(force_update=True)

        mail_content = [f"Facebook album changes as of {datetime.now(UTC)}"]
        
        token = tracker.get_current_access_token()
        if tracker.get_token_status(token) == "session_expires_soon":
            mail_content.append("\nWARNING! Access token session expires in <7 days\n")
        
        if not any(list(changes.values())):
            mail_content.append("==================\nNo changes")
    
        for change, changed_data in changes.items():
            if not changed_data:
                continue

            mail_content.append("\n==================")
            mail_content.append(change)
            mail_content.append("==================")
            if change == "added":
                mail_content.append(
                    "Note: New dog pages are created as Need Offer, location Spain"
                )
            if not changed_data:
                mail_content.append("None")
            for key, val in changed_data.items():
                if change == "custom_albums":
                    mail_content.append(f"{key}: {val.get('link', '')}")
                elif change == "added":
                    mail_content.append(f"{key}: \n\tAlbum name: {val['facebook_album_name']}\n\tPage title: {val['page_title']}")
                else:
                    mail_content.append(f"{key}: {val}")
                    
        mail_content = "\n".join(mail_content)
        self.stdout.write(mail_content)
        if email:
            send_mail(
                subject="Facebook album report",
                message=mail_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.SUPPORT_EMAIL]
            )


