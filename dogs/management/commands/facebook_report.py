from django.core.management.base import BaseCommand

from dogs.models import FacebookAlbumTracker


class Command(BaseCommand):
    help = 'report Facebook changes'

    def handle(self, *args, **options):
        tracker = FacebookAlbumTracker()
        new_data = tracker.fetch_all()
        changes = tracker.report_changes(new_data)

        for change, changed_data in changes.items():
            if changed_data:
                print("==============================================")
                print(change)
                print("==============================================")
            for key, val in changed_data.items():
                if change != "custom_albums":
                    print(f"{key}: {val}")
                else:
                    print(key)
            print("\n")
