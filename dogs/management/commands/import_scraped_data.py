import json
from pathlib import Path

from django.core.management.base import BaseCommand

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
        tracker = FacebookAlbumTracker()

        total = len(albums)
        for i, (album_id, data) in enumerate(albums.items(), start=1):
            self.stdout.write(f"Updating non-api album {i} of {total}")
            tracker.albums_obj.update_album(album_id, data)

            page = DogPage.objects.filter(facebook_album_id=album_id).first()
            if page is None:
                self.stdout.write(f"Page for album id {album_id} not found, skipping")
                continue
            self.stdout.write(f"Creating gallery images for album id {album_id}")
            page_image_ids = page.gallery_images.values_list("fb_image_id", flat=True)
            for image in data["images"]:
                if image["id"] not in page_image_ids:
                    tracker.create_gallery_image(page, image["id"], image["image_url"])
