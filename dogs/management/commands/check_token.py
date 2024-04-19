from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.core.mail import send_mail

from dogs.models import FacebookAlbumTracker, DogPage


class Command(BaseCommand):
    help = ("Check Facebook token; check both the current token and the "
           "next one that will be generated from the short-lived token "
           "found at FB_ACCESS_TOKEN")

    def handle(self, **kwargs):
        tracker = FacebookAlbumTracker()

        current_token = tracker.get_current_access_token()
        next_token = settings.FB_ACCESS_TOKEN
        
        self.stdout.write(f"Current token status: {tracker.get_token_status(current_token)}")
        self.stdout.write(f"Next token status: {tracker.get_token_status(next_token)}")
        
