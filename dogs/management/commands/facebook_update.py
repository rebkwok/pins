from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.core.mail import send_mail

from dogs.models import FacebookAlbumTracker, DogPage


class Command(BaseCommand):
    help = 'update Facebook albums'

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-ix",
            type=int,
            help="start from index",
        )
        parser.add_argument(
            "--to-ix",
            type=int,
            help="to index"
        )
        parser.add_argument(
            "--album-ids",
            nargs='+',
            default=[]
        )

        return super().add_arguments(parser)

    def handle(self, from_ix, to_ix, album_ids, **kwargs):
        if not album_ids:
            album_ids = list(DogPage.objects.filter(custom_album_data__isnull=True).values_list("facebook_album_id", flat=True))        
            if to_ix is None or to_ix > len(album_ids):
                to_ix = len(album_ids)
            album_ids = album_ids[from_ix:to_ix]
        
        tracker = FacebookAlbumTracker()
        tracker.update_albums(album_ids, force_update=True)
