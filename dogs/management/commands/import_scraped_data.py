from datetime import datetime
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.core.mail import send_mail

from dogs.models import FacebookAlbumTracker, DogPage


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
        pages = DogPage.objects.filter(facebook_album_id__in=albums)
        for page in pages:
            page.custom_album_data["images"] = albums[page.facebook_album_id]["images"]
            page.save()
