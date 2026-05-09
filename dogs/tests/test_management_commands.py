from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from dogs.models import FacebookAlbums


pytestmark = pytest.mark.django_db


@pytest.fixture
def albums_obj():
    return FacebookAlbums.instance()


@pytest.fixture
def mock_tracker():
    with patch("dogs.management.commands.sync_facebook.FacebookAlbumTracker") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def mock_token_manager():
    with patch("dogs.management.commands.sync_facebook.FacebookTokenManager") as mock_cls:
        instance = MagicMock()
        instance.get_current_access_token.return_value = "valid_token"
        instance.get_token_status.return_value = "ok"
        mock_cls.return_value = instance
        yield instance


def run_sync(args=None, **kwargs):
    out = StringIO()
    call_command("sync_facebook", *(args or []), stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


NO_CHANGE_RESULT = {
    "added": {},
    "removed": {},
    "changed": {},
    "moved": {},
    "failed_to_delete": set(),
}


# ---------------------------------------------------------------------------
# Full sync — report output
# ---------------------------------------------------------------------------

class TestSyncFacebookFullSync:

    def test_no_changes_output(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = NO_CHANGE_RESULT.copy()
        output = run_sync()
        assert "No changes" in output

    def test_added_albums_appear_in_output(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = {
            **NO_CHANGE_RESULT,
            "added": {"album1": {"facebook_album_name": "Bella - in Spain", "page_title": "Bella"}},
        }
        output = run_sync()
        assert "album1" in output
        assert "Bella" in output

    def test_changed_title_note_appears(self, albums_obj, mock_token_manager, mock_tracker):
        """The 'changed' section note must read correctly (regression: was 'changes' not 'changed')."""
        mock_tracker.update_all.return_value = {
            **NO_CHANGE_RESULT,
            "changed": {"album1": "Bella - happily homed (previously Bella - in Spain)"},
        }
        output = run_sync()
        assert "changes to album title only" in output

    def test_moved_pages_appear_in_output(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = {
            **NO_CHANGE_RESULT,
            "moved": {"album1": {"from": "Needs Offer", "to": "In foster"}},
        }
        output = run_sync()
        assert "album1" in output
        assert "Needs Offer" in output
        assert "In foster" in output

    def test_failed_to_delete_appears_in_output(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = {
            **NO_CHANGE_RESULT,
            "removed": {"album1": "Bella - in Spain"},
            "failed_to_delete": {"album1"},
        }
        output = run_sync()
        assert "failed_to_delete" in output
        assert "album1" in output


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

class TestSyncFacebookEmail:

    def test_sends_email_when_flag_set(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = NO_CHANGE_RESULT.copy()
        with patch("dogs.management.commands.sync_facebook.send_mail") as mock_mail:
            run_sync(["--email"])
        mock_mail.assert_called_once()

    def test_no_email_without_flag(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = NO_CHANGE_RESULT.copy()
        with patch("dogs.management.commands.sync_facebook.send_mail") as mock_mail:
            run_sync()
        mock_mail.assert_not_called()

    def test_email_subject_has_correct_date_format(self, albums_obj, mock_token_manager, mock_tracker, freezer):
        """Email subject strftime must use %Y-%m-%d %H:%M (regression: %M/%m were swapped)."""
        freezer.move_to("2024-06-15T14:30:00+00:00")
        mock_tracker.update_all.return_value = NO_CHANGE_RESULT.copy()
        with patch("dogs.management.commands.sync_facebook.send_mail") as mock_mail:
            run_sync(["--email"])
        subject = mock_mail.call_args.kwargs["subject"]
        assert "2024-06-15" in subject
        assert "14:30" in subject

    def test_email_subject_includes_no_changes_marker(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = NO_CHANGE_RESULT.copy()
        with patch("dogs.management.commands.sync_facebook.send_mail") as mock_mail:
            run_sync(["--email"])
        subject = mock_mail.call_args.kwargs["subject"]
        assert "NO CHANGES" in subject

    def test_email_subject_omits_no_changes_when_there_are_changes(self, albums_obj, mock_token_manager, mock_tracker):
        mock_tracker.update_all.return_value = {
            **NO_CHANGE_RESULT,
            "added": {"album1": {"facebook_album_name": "Bella", "page_title": "Bella"}},
        }
        with patch("dogs.management.commands.sync_facebook.send_mail") as mock_mail:
            run_sync(["--email"])
        subject = mock_mail.call_args.kwargs["subject"]
        assert "NO CHANGES" not in subject


# ---------------------------------------------------------------------------
# Token errors
# ---------------------------------------------------------------------------

class TestSyncFacebookTokenErrors:

    def test_expired_token_sends_alert_email(self, albums_obj, mock_tracker):
        with patch("dogs.management.commands.sync_facebook.FacebookTokenManager") as mock_cls:
            mgr = MagicMock()
            mgr.get_current_access_token.return_value = "expired_token"
            mgr.get_token_status.return_value = "expired"
            mock_cls.return_value = mgr
            with patch("dogs.management.commands.sync_facebook.send_mail") as mock_mail:
                run_sync(["--email"])
        mock_mail.assert_called_once()
        subject = mock_mail.call_args.kwargs["subject"]
        assert "error" in subject.lower() or "expired" in subject.lower()

    def test_expired_token_does_not_run_sync(self, albums_obj, mock_tracker):
        with patch("dogs.management.commands.sync_facebook.FacebookTokenManager") as mock_cls:
            mgr = MagicMock()
            mgr.get_current_access_token.return_value = "expired_token"
            mgr.get_token_status.return_value = "expired"
            mock_cls.return_value = mgr
            run_sync()
        mock_tracker.update_all.assert_not_called()


# ---------------------------------------------------------------------------
# Specific album update mode
# ---------------------------------------------------------------------------

class TestSyncFacebookAlbumUpdate:

    def test_album_ids_flag_calls_update_albums(self, albums_obj, mock_token_manager, mock_tracker):
        run_sync(["--album-ids", "album1", "album2"])
        mock_tracker.update_albums.assert_called_once_with(["album1", "album2"], force_update=True)
        mock_tracker.update_all.assert_not_called()


# ---------------------------------------------------------------------------
# Check mode
# ---------------------------------------------------------------------------

class TestSyncFacebookCheckMode:

    def test_check_mode_does_not_call_update_all(self, albums_obj, mock_token_manager, mock_tracker):
        run_sync(["--check"])
        mock_tracker.update_all.assert_not_called()

    def test_check_mode_outputs_stored_data(self, albums_obj, mock_token_manager, mock_tracker):
        from dogs.tests.test_models import DogsIndexPageFactory, DogStatusPageFactory
        index = DogsIndexPageFactory(parent=None)
        status_page = DogStatusPageFactory(parent=index, title="Needs Offer")
        albums_obj.update_album("album1", {"name": "Bella"})
        output = run_sync(["--check"])
        assert "Needs Offer" in output
