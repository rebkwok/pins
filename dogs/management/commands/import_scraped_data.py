import json
from pathlib import Path

from django.core.management.base import BaseCommand

from dogs.models import FacebookAlbumTracker


class Command(BaseCommand):
    help = 'update Facebook albums'

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            "-p",
            type=Path,
            help="Path to scraped json file",
        )
        return super().add_arguments(parser)

    def handle(self, path, **kwargs):
        data = json.loads(Path(path).read_text())
        albums = data["non_api_albums"]
        tracker = FacebookAlbumTracker()

        for album_id, data in albums.items():
            tracker.albums_obj.update_album(album_id, data)

