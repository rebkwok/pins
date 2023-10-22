import requests

from tqdm import tqdm
from django.core.management.base import BaseCommand

from dogs.models import FacebookAlbums


class Command(BaseCommand):
    help = 'remove expired image urls'

    def handle(self, **kwargs):
        albums_container = FacebookAlbums.instance()
        albums_data = dict(albums_container.albums)

        total = len(albums_data)
        for i, (album_id, album) in enumerate(albums_data.items()):
            self.stdout.write(f"Checking album {i + 1} of {total}")

            new_images = []
            for image in tqdm(album["images"], desc=f"Checking images for {album_id}"):
                try:
                    resp = requests.get(image["image_url"])
                    if resp.status_code == 200:
                        new_images.append(image)
                except requests.exceptions.ConnectionError:
                    # ignore connection error, happens when the URL is no longer 
                    # accessible at all
                    ...
            albums_container.albums[album_id]["images"] = new_images
            albums_container.save()
