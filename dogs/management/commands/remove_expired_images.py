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
                "images": []
            }
            for field in ["description", "updated_time"]: 
                if field in album:
                    new_albums_data[album_id][field] = album[field]
            self.stdout.write(f"Checking album {i + 1} of {total}")

            images = []
            self.stdout.write(f"Existing image count: {len(album['images'])}")
            for image in tqdm(album["images"], desc=f"Checking images for {album_id}"):
                try:
                    resp = requests.get(image["image_url"])
                    if resp.status_code == 200:
                        images.append(image)
                    else:
                        self.stdout.write("Expired url")
                except requests.exceptions.ConnectionError:
                    # ignore connection error, happens when the URL is no longer 
                    # accessible at all
                    self.stdout.write("Inaccessible url")
            self.stdout.write(f"New image count: {len(images)}")
            new_albums_data[album_id]["images"] = images
        albums_container.update_all(new_albums_data)
