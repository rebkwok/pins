from django.conf import settings
from django.core.management.base import BaseCommand

from dogs.models import FacebookAlbumTracker, DogPage, DogStatusPage

from django.core.mail import send_mail


class Command(BaseCommand):
    help = 'Check stored facebook data'

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            action="store_true",
            help="Send to support email",
        )
        return super().add_arguments(parser)

    def handle(self, email, **kwargs):
        tracker = FacebookAlbumTracker()

        message = []
        for status_page in DogStatusPage.objects.all():
            message.append(f"============{status_page.title}===========")
            
            dog_pages = status_page.get_children()
            for page in dog_pages:
                saved_data = tracker.albums_obj.get_album(page.specific.facebook_album_id)
                if not saved_data:
                    message.append(f"Site: {page} - {page.get_parent().title} / Facebook: removed")
                else:
                    message.append(f"Site: {page.title} - {page.get_parent().title} ({page.specific.location})/ Facebook: - {saved_data['name']}")

        self.stdout.write('\n'.join(message)) 
        
        self.stdout.write("Sending email")
        send_mail(
            subject="album report",
            message='\n'.join(message),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.SUPPORT_EMAIL]
        )