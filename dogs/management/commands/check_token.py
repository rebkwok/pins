from django.core.management.base import BaseCommand

from dogs.models import FacebookTokenManager


class Command(BaseCommand):
    help = ("Check Facebook token status. Checks both the current stored token "
            "and the short-lived seed token from FB_ACCESS_TOKEN.")

    def handle(self, **kwargs):
        from django.conf import settings
        manager = FacebookTokenManager()
        current_token = manager.get_current_access_token()
        next_token = settings.FB_ACCESS_TOKEN

        self.stdout.write(f"Current token status: {manager.get_token_status(current_token)}")
        self.stdout.write(f"Next token status: {manager.get_token_status(next_token)}")
