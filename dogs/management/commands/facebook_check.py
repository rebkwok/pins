from django.core.management.base import BaseCommand

from dogs.models import FacebookAlbumTracker, DogPage, DogStatusPage


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

        for status_page in DogStatusPage.objects.all():
            self.stdout.write(f"============{status_page.title}===========")
            dog_pages = status_page.get_children()
            for page in dog_pages:
                saved_data = tracker.albums_obj.get_album(page.specific.facebook_album_id)
                if not saved_data:
                    self.stdout.write(f"Site: {page} - {page.get_parent().title} / Facebook: removed")
                else:
                    self.stdout.write(f"Site: {page.title} - {page.get_parent().title} ({page.specific.location})/ Facebook: - {saved_data['name']}")