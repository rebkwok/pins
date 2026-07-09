from datetime import datetime, UTC

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.urls import reverse

from dogs.models import FacebookAlbumTracker, FacebookTokenManager, DogPage


class Command(BaseCommand):
    help = 'Sync Facebook albums, report changes, and optionally send email'

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            action="store_true",
            help="Send report to support email",
        )
        parser.add_argument(
            "--album-ids",
            nargs='+',
            default=[],
            help="Update specific album IDs only",
        )
        parser.add_argument(
            "--from-ix",
            type=int,
            help="Start from index (when updating all albums)",
        )
        parser.add_argument(
            "--to-ix",
            type=int,
            help="End at index (when updating all albums)",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Print stored album data without fetching from Facebook",
        )
        parser.add_argument(
            "--force-update",
            action="store_true",
            help="Force all album photos to be re-fetched from Facebook, ignoring last_fetched",
        )

    def handle(self, email, album_ids, from_ix, to_ix, check, force_update, **kwargs):
        token_manager = FacebookTokenManager()
        token = token_manager.get_current_access_token()
        status = token_manager.get_token_status(token)

        renewal_msg = (
            "Generate a new Page token at https://developers.facebook.com/tools/explorer/ "
            "and extend it using the Access Token Tool. Then update the FB_ACCESS_TOKEN "
            "env variable.\n\n"
            "If existing token has expired, also delete .fb_access_token\n\n"
            "Check it works by running:\n"
            "./manage.py check_token"
        )

        if status == "expired":
            if email:
                send_mail(
                    subject="Facebook token error!",
                    message=f"Access token has expired.\n{renewal_msg}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.SUPPORT_EMAIL],
                )
            self.stderr.write("Access token has expired.")
            return

        if status == "expires_soon":
            if email:
                send_mail(
                    subject="Facebook token expiring soon!",
                    message=f"Access token expires within 24 hours.\n\n{renewal_msg}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.SUPPORT_EMAIL],
                )
            self.stderr.write("Warning: access token expires within 24 hours.")

        if check:
            self._run_check()
            return

        tracker = FacebookAlbumTracker()

        if album_ids or from_ix is not None or to_ix is not None:
            if not album_ids:
                all_ids = list(DogPage.objects.filter(
                    facebook_album_id__isnull=False
                ).values_list("facebook_album_id", flat=True))
                to_ix = to_ix if to_ix is not None and to_ix <= len(all_ids) else len(all_ids)
                album_ids = all_ids[from_ix:to_ix]
            tracker.update_albums(album_ids, force_update=True)
            return

        self._run_full_sync(tracker, email, force_update=force_update)

    def _run_full_sync(self, tracker, send_email, force_update=False):
        now = datetime.now(UTC)
        mail_content = [f"Facebook album changes as of {now}"]

        changes = tracker.update_all(force_update=force_update)
        failed_to_delete = changes.pop("failed_to_delete")

        # Albums whose title changed AND whose page was moved belong in one section only.
        changed_and_moved_ids = set(changes["changed"]) & set(changes["moved"])
        changes["changed_and_moved"] = {
            album_id: {"description": changes["changed"].pop(album_id), **changes["moved"].pop(album_id)}
            for album_id in changed_and_moved_ids
        }

        has_changes = any(changes[k] for k in ("added", "removed", "changed", "moved", "changed_and_moved"))

        if not has_changes:
            mail_content.append("==================\nNo changes")

        section_notes = {
            "added": "Note: New dog pages are created as Needs Offer, location Spain (unless title indicates otherwise)",
            "changed": "Note: changes to album title only",
            "moved": "Note: pages moved based on updated album title",
            "changed_and_moved": "Note: album title changed and page was automatically moved to a new status section",
        }

        for change, changed_data in changes.items():
            if not changed_data:
                continue
            mail_content.append("\n==================")
            mail_content.append(change)
            mail_content.append("==================")
            if change in section_notes:
                mail_content.append(section_notes[change])
            for key, val in changed_data.items():
                if change == "added":
                    mail_content.append(
                        f"{key}: \n\tAlbum name: {val['facebook_album_name']}\n\tPage title: {val['page_title']}"
                    )
                elif change == "moved":
                    mail_content.append(f"{key}: {val['page_title']} ({val['from']} → {val['to']})")
                elif change == "changed_and_moved":
                    mail_content.append(
                        f"{key}: {val['description']} — {val['page_title']} moved {val['from']} → {val['to']}"
                    )
                else:
                    mail_content.append(f"{key}: {val}")

        if failed_to_delete:
            mail_content.append("\n==================")
            mail_content.append("failed_to_delete")
            mail_content.append("==================")
            for album_id in failed_to_delete:
                removed = changes.get("removed", {})
                mail_content.append(f"{album_id}: {removed.get(album_id, '')}")

        changes_url = settings.WAGTAILADMIN_BASE_URL + reverse('facebook_changes')
        mail_content.append(f"\nView and acknowledge changes: {changes_url}")

        report = "\n".join(mail_content)
        self.stdout.write(report)

        if send_email:
            subject = "album report "
            if not has_changes:
                subject += "(NO CHANGES) "
            send_mail(
                subject=f"{subject}- {now.strftime('%Y-%m-%d %H:%M')}",
                message=report,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.SUPPORT_EMAIL],
            )

    def _run_check(self):
        from dogs.models import DogStatusPage, FacebookAlbums
        tracker_albums = FacebookAlbums.instance()
        message = []
        for status_page in DogStatusPage.objects.all():
            message.append(f"============{status_page.title}===========")
            for page in status_page.get_children():
                saved_data = tracker_albums.get_album(page.specific.facebook_album_id)
                if not saved_data:
                    message.append(f"Site: {page} - {page.get_parent().title} / Facebook: removed")
                else:
                    message.append(
                        f"Site: {page.title} - {page.get_parent().title} "
                        f"({page.specific.location}) / Facebook: {saved_data['name']}"
                    )
        self.stdout.write('\n'.join(message))
