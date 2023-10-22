import requests

from tqdm import tqdm
from django.core.management.base import BaseCommand

from dogs.models import FacebookAlbums


class Command(BaseCommand):
    help = 'remove expired image urls'

    def handle(self, **kwargs):
        albums_container = FacebookAlbums.instance()

        new_albums_data = {}

        total = len(albums_container.albums)
        for i, (album_id, album) in enumerate(albums_container.albums.items()):
            new_albums_data[album_id] = {
                "link": album["link"],
                "count": album["count"],
                "name": album["name"],
                "description": album.get("description"),
                "updated_time": album.get("updated_time"),
                "images": []
            }
            self.stdout.write(f"Checking album {i + 1} of {total}")

            images = []
            for image in tqdm(album["images"], desc=f"Checking images for {album_id}"):
                try:
                    resp = requests.get(image["image_url"])
                    if resp.status_code == 200:
                        images.append(image)
                except requests.exceptions.ConnectionError:
                    # ignore connection error, happens when the URL is no longer 
                    # accessible at all
                    ...
            new_albums_data[album_id]["images"] = images
        albums_container.update_all(new_albums_data)
