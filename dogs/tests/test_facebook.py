from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

import wagtail_factories

from dogs.models import (
    DogsIndexPage,
    DogStatusPage,
    DogPage,
    FacebookAlbums,
    FacebookAlbumTracker,
    FacebookTokenManager,
    FOSTER_RE,
    HAPPILY_HOMED_RE,
    get_target_status_title,
)


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

class DogsIndexPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = DogsIndexPage


class DogStatusPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = DogStatusPage


class DogPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = DogPage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dogs_index(root_page):
    return DogsIndexPageFactory(parent=root_page)


@pytest.fixture
def needs_offer_page(dogs_index):
    return DogStatusPageFactory(parent=dogs_index, title="Needs Offer")


@pytest.fixture
def in_foster_page(dogs_index):
    return DogStatusPageFactory(parent=dogs_index, title="In foster")


@pytest.fixture
def happily_homed_page(dogs_index):
    return DogStatusPageFactory(parent=dogs_index, title="Happily homed")


@pytest.fixture
def status_pages(needs_offer_page, in_foster_page, happily_homed_page):
    return {
        "needs_offer": needs_offer_page,
        "in_foster": in_foster_page,
        "happily_homed": happily_homed_page,
    }


@pytest.fixture
def albums_obj():
    return FacebookAlbums.instance()


# ---------------------------------------------------------------------------
# FacebookAlbums.instance() singleton
# ---------------------------------------------------------------------------

class TestFacebookAlbumsInstance:
    def test_creates_with_pk_1_on_first_call(self):
        obj = FacebookAlbums.instance()
        assert obj.pk == 1

    def test_returns_same_row_on_repeated_calls(self):
        FacebookAlbums.instance()
        FacebookAlbums.instance()
        assert FacebookAlbums.objects.count() == 1

    def test_existing_row_reused(self):
        first = FacebookAlbums.instance()
        second = FacebookAlbums.instance()
        assert first.pk == second.pk


# ---------------------------------------------------------------------------
# FacebookAlbums.is_rate_limited (pure property)
# ---------------------------------------------------------------------------

class TestFacebookAlbumsRateLimit:
    def test_not_rate_limited_by_default(self, albums_obj):
        assert not albums_obj.is_rate_limited

    def test_rate_limited_within_60_minutes(self, albums_obj, freezer):
        albums_obj.set_rate_limit()
        freezer.tick(timedelta(minutes=59))
        albums_obj.refresh_from_db()
        assert albums_obj.is_rate_limited

    def test_not_rate_limited_after_60_minutes(self, albums_obj, freezer):
        albums_obj.set_rate_limit()
        freezer.tick(timedelta(minutes=61))
        albums_obj.refresh_from_db()
        assert not albums_obj.is_rate_limited

    def test_is_rate_limited_does_not_clear_rate_limited_at(self, albums_obj):
        """is_rate_limited must not have the side effect of clearing rate_limited_at."""
        albums_obj.set_rate_limit()
        _ = albums_obj.is_rate_limited  # access property
        albums_obj.refresh_from_db()
        assert albums_obj.rate_limited_at is not None


# ---------------------------------------------------------------------------
# FacebookAlbums reporting_baseline / acknowledge
# ---------------------------------------------------------------------------

class TestFacebookAlbumsReportingBaseline:
    def test_reporting_baseline_starts_empty(self, albums_obj):
        assert albums_obj.reporting_baseline == {}

    def test_update_all_does_not_advance_baseline(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}})
        albums_obj.refresh_from_db()
        assert albums_obj.reporting_baseline == {}

    def test_acknowledge_sets_baseline_to_current_albums(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}})
        albums_obj.acknowledge()
        albums_obj.refresh_from_db()
        assert albums_obj.reporting_baseline == {"1": {"name": "dog 1"}}

    def test_acknowledge_after_further_update(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}})
        albums_obj.acknowledge()
        albums_obj.update_all({"1": {"name": "dog 1 updated"}})
        albums_obj.acknowledge()
        albums_obj.refresh_from_db()
        assert albums_obj.reporting_baseline == {"1": {"name": "dog 1 updated"}}


# ---------------------------------------------------------------------------
# FacebookAlbums.album_recently_fetched / last_fetched
# ---------------------------------------------------------------------------

class TestAlbumRecentlyFetched:
    def test_not_recently_fetched_when_no_last_fetched(self, albums_obj):
        albums_obj.update_album("1", {"name": "dog 1"})
        assert not albums_obj.album_recently_fetched("1")

    def test_recently_fetched_within_threshold(self, albums_obj, freezer):
        freezer.move_to("2024-06-01T12:00:00+00:00")
        albums_obj.update_album("1", {"name": "dog 1", "last_fetched": "2024-06-01T12:00:00+00:00"})
        freezer.tick(timedelta(minutes=30))
        assert albums_obj.album_recently_fetched("1")

    def test_not_recently_fetched_beyond_threshold(self, albums_obj, freezer):
        freezer.move_to("2024-06-01T12:00:00+00:00")
        albums_obj.update_album("1", {"name": "dog 1", "last_fetched": "2024-06-01T10:00:00+00:00"})
        assert not albums_obj.album_recently_fetched("1")

    def test_not_recently_fetched_unknown_album(self, albums_obj):
        assert not albums_obj.album_recently_fetched("nonexistent")


# ---------------------------------------------------------------------------
# FacebookAlbums.pending_changes
# ---------------------------------------------------------------------------

class TestFacebookAlbumsPendingChanges:
    def test_no_pending_changes_when_baseline_matches_albums(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}})
        albums_obj.acknowledge()
        assert not any(albums_obj.pending_changes().values())

    def test_detects_added(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}, "2": {"name": "dog 2"}})
        albums_obj.reporting_baseline = {"1": {"name": "dog 1"}}
        albums_obj.save()
        changes = albums_obj.pending_changes()
        assert "2" in changes["added"]

    def test_detects_removed(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}})
        albums_obj.reporting_baseline = {"1": {"name": "dog 1"}, "2": {"name": "dog 2"}}
        albums_obj.save()
        changes = albums_obj.pending_changes()
        assert "2" in changes["removed"]

    def test_detects_changed_title(self, albums_obj):
        albums_obj.update_all({"1": {"name": "Bella - happily homed"}})
        albums_obj.reporting_baseline = {"1": {"name": "Bella - in Spain"}}
        albums_obj.save()
        changes = albums_obj.pending_changes()
        assert "1" in changes["changed"]


# ---------------------------------------------------------------------------
# FacebookAlbumTracker.report_changes (diffs against reporting_baseline)
# ---------------------------------------------------------------------------

class TestReportChanges:
    def test_diffs_against_reporting_baseline_not_albums(self, albums_obj):
        albums_obj.albums = {"1": {"name": "dog 1"}, "2": {"name": "dog 2"}}
        albums_obj.reporting_baseline = {"1": {"name": "dog 1"}}
        albums_obj.save()

        tracker = FacebookAlbumTracker()
        changes = tracker.report_changes({"1": {"name": "dog 1"}, "2": {"name": "dog 2"}})
        assert "2" in changes["added"]

    def test_detects_added(self, albums_obj):
        tracker = FacebookAlbumTracker()
        changes = tracker.report_changes({"1": {"name": "dog 1"}})
        assert changes["added"] == {"1": "dog 1"}
        assert changes["removed"] == {}
        assert changes["changed"] == {}

    def test_detects_removed(self, albums_obj):
        albums_obj.reporting_baseline = {"1": {"name": "dog 1"}}
        albums_obj.save()
        tracker = FacebookAlbumTracker()
        changes = tracker.report_changes({})
        assert changes["removed"] == {"1": "dog 1"}

    def test_detects_changed_title(self, albums_obj):
        albums_obj.reporting_baseline = {"1": {"name": "Bella - in Spain"}}
        albums_obj.save()
        tracker = FacebookAlbumTracker()
        changes = tracker.report_changes({"1": {"name": "Bella - happily homed"}})
        assert "1" in changes["changed"]
        assert "Bella - happily homed" in changes["changed"]["1"]
        assert "Bella - in Spain" in changes["changed"]["1"]

    def test_no_changes_returns_empty(self, albums_obj):
        albums_obj.reporting_baseline = {"1": {"name": "dog 1"}}
        albums_obj.save()
        tracker = FacebookAlbumTracker()
        changes = tracker.report_changes({"1": {"name": "dog 1"}})
        assert not any(changes.values())


# ---------------------------------------------------------------------------
# FacebookAlbumTracker.update_all — baseline auto-advance
# ---------------------------------------------------------------------------

class TestUpdateAllBaselineAdvance:
    def test_auto_advances_baseline_when_no_changes(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}})
        albums_obj.reporting_baseline = {"1": {"name": "dog 1"}}
        albums_obj.save()

        tracker = FacebookAlbumTracker()
        with patch.object(tracker, 'fetch_all', return_value={"1": {"name": "dog 1"}}):
            with patch.object(tracker, 'create_new_pages', return_value={}):
                with patch.object(tracker, 'remove_pages', return_value=set()):
                    with patch.object(tracker, 'apply_title_routing', return_value={}):
                        tracker.update_all()

        albums_obj.refresh_from_db()
        # baseline should now equal albums (auto-advanced)
        assert albums_obj.reporting_baseline == albums_obj.albums

    def test_does_not_advance_baseline_when_changes_exist(self, albums_obj):
        albums_obj.update_all({"1": {"name": "dog 1"}})
        albums_obj.reporting_baseline = {}
        albums_obj.save()

        tracker = FacebookAlbumTracker()
        new_data = {"1": {"name": "dog 1"}, "2": {"name": "dog 2"}}
        with patch.object(tracker, 'fetch_all', return_value=new_data):
            with patch.object(tracker, 'create_new_pages', return_value={
                "2": {"facebook_album_name": "dog 2", "page_title": "Dog 2"}
            }):
                with patch.object(tracker, 'remove_pages', return_value=set()):
                    with patch.object(tracker, 'apply_title_routing', return_value={}):
                        tracker.update_all()

        albums_obj.refresh_from_db()
        assert albums_obj.reporting_baseline == {}


# ---------------------------------------------------------------------------
# FacebookAlbumTracker.update_all — integration
# ---------------------------------------------------------------------------

class TestUpdateAllIntegration:
    """End-to-end tests for update_all covering new pages, recreated pages,
    and title-based routing — with only network calls mocked out."""

    ALBUM_DATA = {
        "album1": {"name": "Bella - in Spain", "updated_time": "2024-01-01T00:00:00"},
        "album2": {"name": "Rex - in Spain", "updated_time": "2024-01-01T00:00:00"},
        "album3": {"name": "Luna - in Spain", "updated_time": "2024-01-01T00:00:00"},
        "album4": {"name": "Max - in Spain", "updated_time": "2024-01-01T00:00:00"},
    }

    def test_full_lifecycle(self, albums_obj, status_pages):
        tracker = FacebookAlbumTracker()

        # 1. Run update_all — 4 new albums, 4 new pages created
        with patch.object(tracker, 'fetch_all', return_value=self.ALBUM_DATA):
            with patch.object(DogPage, 'update_facebook_info'):
                tracker.update_all()

        # 2. pending_changes reports all 4 as added, nothing else
        albums_obj.refresh_from_db()
        pending = albums_obj.pending_changes()
        assert set(pending['added']) == {"album1", "album2", "album3", "album4"}
        assert not pending['removed']
        assert not pending['changed']
        assert not pending['moved']
        assert not pending['recreated']

        # 3. Acknowledge — baseline advances, no further pending changes
        albums_obj.acknowledge()
        tracker.albums_obj.refresh_from_db()
        assert not any(tracker.albums_obj.pending_changes().values())

        # 4. Delete one page, then run update_all again with the same album data
        DogPage.objects.get(facebook_album_id="album1").delete()

        with patch.object(tracker, 'fetch_all', return_value=self.ALBUM_DATA):
            with patch.object(DogPage, 'update_facebook_info'):
                tracker.update_all()

        # 5. Deleted page is recreated and reported in pending_changes as recreated
        albums_obj.refresh_from_db()
        assert DogPage.objects.filter(facebook_album_id="album1").exists()
        pending = albums_obj.pending_changes()
        assert "album1" in pending['recreated']
        assert not pending['added']
        assert not pending['removed']
        assert not pending['changed']

        # 6. Acknowledge
        albums_obj.acknowledge()
        tracker.albums_obj.refresh_from_db()

        # 7. Run update_all with two changed album titles:
        #    album1 title now matches the foster keyword → page should move
        #    album2 title changes but does not match any routing keyword
        changed_data = {
            **self.ALBUM_DATA,
            "album1": {"name": "Bella - in foster", "updated_time": "2024-01-02T00:00:00"},
            "album2": {"name": "Rex - still in Spain", "updated_time": "2024-01-02T00:00:00"},
        }

        with patch.object(tracker, 'fetch_all', return_value=changed_data):
            with patch.object(DogPage, 'update_facebook_info'):
                tracker.update_all()

        # 8. album1's page has moved to In foster; both title changes and
        #    the move all appear in pending_changes
        albums_obj.refresh_from_db()
        bella = DogPage.objects.get(facebook_album_id="album1")
        assert bella.get_parent().title.lower() == "in foster"

        pending = albums_obj.pending_changes()
        # album1 changed title AND moved → appears only in changed_and_moved
        assert "album1" in pending['changed_and_moved']
        assert "album1" not in pending['moved']
        assert "album1" not in pending['changed']
        # album2 title changed but did not move → appears only in changed
        assert "album2" in pending['changed']
        assert "album2" not in pending['changed_and_moved']

        # 9. Acknowledge
        albums_obj.acknowledge()
        tracker.albums_obj.refresh_from_db()

        # 10. Manually move bella (album1) out of In foster back to Needs Offer.
        #     The album title has not changed — still "Bella - in foster".
        bella = DogPage.objects.get(facebook_album_id="album1")
        needs_offer = DogStatusPage.objects.get(pk=status_pages["needs_offer"].pk)
        bella.move(needs_offer, pos="last-child")

        # 11. Run update_all with the same data (no title changes)
        with patch.object(tracker, 'fetch_all', return_value=changed_data):
            with patch.object(DogPage, 'update_facebook_info'):
                tracker.update_all()

        # 12. update_all detects bella is in the wrong status page and moves her
        #     back. The move appears in pending_changes as 'moved' only — not
        #     'changed' or 'changed_and_moved' because the album title is unchanged.
        albums_obj.refresh_from_db()
        bella.refresh_from_db()
        assert bella.get_parent().title.lower() == "in foster"

        pending = albums_obj.pending_changes()
        assert "album1" in pending['moved']
        assert "album1" not in pending['changed']
        assert "album1" not in pending['changed_and_moved']


# ---------------------------------------------------------------------------
# Title-based routing helpers
# ---------------------------------------------------------------------------

class TestStatusRoutingRegex:
    @pytest.mark.parametrize("title", [
        "Bella - in foster",
        "Rex - coming to foster",
        "Luna - travels to foster",
        "Max - fostered",
        "Pip - foster home",
        "Nino - in foster in UK",
        "Dog - In Foster",          # case insensitive
        "Dog - FOSTER",
    ])
    def test_foster_regex_matches(self, title):
        assert FOSTER_RE.search(title)

    def test_foster_regex_does_not_match_unrelated(self):
        assert not FOSTER_RE.search("Bella - happily homed")
        assert not FOSTER_RE.search("Bella - in Spain, needs offer")

    @pytest.mark.parametrize("title", [
        "Bella - happily homed",
        "Rex - Happily Homed",
        "Luna - happily  homed",    # multiple spaces
    ])
    def test_happily_homed_regex_matches(self, title):
        assert HAPPILY_HOMED_RE.search(title)

    def test_happily_homed_does_not_match_homed_alone(self):
        assert not HAPPILY_HOMED_RE.search("Bella - homed")

    def test_get_target_status_title_foster(self):
        assert get_target_status_title("Bella - in foster") == "In foster"

    def test_get_target_status_title_happily_homed(self):
        assert get_target_status_title("Bella - happily homed") == "Happily homed"

    def test_get_target_status_title_no_match(self):
        assert get_target_status_title("Bella - in Spain, needs offer") is None

    def test_foster_takes_priority_over_happily_homed(self):
        # Contrived but verifies priority order
        assert get_target_status_title("foster and happily homed") == "In foster"


# ---------------------------------------------------------------------------
# FacebookAlbumTracker.create_new_pages — title routing
# ---------------------------------------------------------------------------

class TestCreateNewPagesRouting:

    @pytest.fixture(autouse=True)
    def patch_dog_page_save(self):
        with patch.object(DogPage, 'update_facebook_info'):
            yield

    def test_new_album_foster_keyword_goes_to_in_foster(self, status_pages):
        tracker = FacebookAlbumTracker()
        tracker.create_new_pages({"album1": "Bella - in foster"})
        page = DogPage.objects.get(facebook_album_id="album1")
        assert page.get_parent().specific == status_pages["in_foster"]

    def test_new_album_coming_to_foster_goes_to_in_foster(self, status_pages):
        tracker = FacebookAlbumTracker()
        tracker.create_new_pages({"album1": "Rex - coming to foster"})
        page = DogPage.objects.get(facebook_album_id="album1")
        assert page.get_parent().specific == status_pages["in_foster"]

    def test_new_album_happily_homed_goes_to_happily_homed(self, status_pages):
        tracker = FacebookAlbumTracker()
        tracker.create_new_pages({"album1": "Max - happily homed"})
        page = DogPage.objects.get(facebook_album_id="album1")
        assert page.get_parent().specific == status_pages["happily_homed"]

    def test_new_album_no_keyword_goes_to_needs_offer(self, status_pages):
        tracker = FacebookAlbumTracker()
        tracker.create_new_pages({"album1": "Pip - in Spain, needs offer"})
        page = DogPage.objects.get(facebook_album_id="album1")
        assert page.get_parent().specific == status_pages["needs_offer"]

    def test_dog_name_parsed_from_album_title(self, status_pages):
        tracker = FacebookAlbumTracker()
        tracker.create_new_pages({"album1": "Bella Luna - in Spain, needs offer"})
        page = DogPage.objects.get(facebook_album_id="album1")
        assert page.title == "Bella Luna"

    def test_returns_page_metadata(self, status_pages):
        tracker = FacebookAlbumTracker()
        result = tracker.create_new_pages({"album1": "Bella - in Spain, needs offer"})
        assert result["album1"]["facebook_album_name"] == "Bella - in Spain, needs offer"
        assert result["album1"]["page_title"] == "Bella"


# ---------------------------------------------------------------------------
# FacebookAlbumTracker.apply_title_routing
# ---------------------------------------------------------------------------

class TestApplyTitleRouting:

    @pytest.fixture(autouse=True)
    def patch_dog_page_save(self):
        with patch.object(DogPage, 'update_facebook_info'):
            yield

    def test_moves_page_when_title_matches_foster(self, status_pages):
        page = DogPageFactory(parent=status_pages["needs_offer"], facebook_album_id="album1")
        tracker = FacebookAlbumTracker()
        moved = tracker.apply_title_routing({"album1": "Bella - in foster"})
        page.refresh_from_db()
        assert page.get_parent().specific == status_pages["in_foster"]
        assert "album1" in moved
        assert moved["album1"]["page_title"] == page.title
        assert moved["album1"]["from"] == "Needs Offer"
        assert moved["album1"]["to"] == "In foster"

    def test_moves_page_when_title_matches_happily_homed(self, status_pages):
        page = DogPageFactory(parent=status_pages["needs_offer"], facebook_album_id="album1")
        tracker = FacebookAlbumTracker()
        moved = tracker.apply_title_routing({"album1": "Bella - happily homed"})
        page.refresh_from_db()
        assert page.get_parent().specific == status_pages["happily_homed"]
        assert "album1" in moved

    def test_does_not_move_when_no_keyword(self, status_pages):
        page = DogPageFactory(parent=status_pages["needs_offer"], facebook_album_id="album1")
        tracker = FacebookAlbumTracker()
        moved = tracker.apply_title_routing({"album1": "Bella - new name in Spain"})
        page.refresh_from_db()
        assert page.get_parent().specific == status_pages["needs_offer"]
        assert "album1" not in moved

    def test_does_not_move_page_already_on_correct_status(self, status_pages):
        page = DogPageFactory(parent=status_pages["in_foster"], facebook_album_id="album1")
        tracker = FacebookAlbumTracker()
        moved = tracker.apply_title_routing({"album1": "Bella - in foster"})
        assert "album1" not in moved

    def test_skips_album_with_no_matching_dog_page(self, status_pages):
        tracker = FacebookAlbumTracker()
        moved = tracker.apply_title_routing({"nonexistent": "Bella - in foster"})
        assert "nonexistent" not in moved

    def test_returns_empty_when_no_changed_titles(self, status_pages):
        tracker = FacebookAlbumTracker()
        assert tracker.apply_title_routing({}) == {}


# ---------------------------------------------------------------------------
# DogPage.save() behaviour
# ---------------------------------------------------------------------------

class TestDogPageSave:

    @pytest.fixture(autouse=True)
    def patch_update_fb(self):
        with patch.object(DogPage, 'update_facebook_info') as mock:
            self.mock_update = mock
            yield

    def test_is_new_true_for_brand_new_page(self, needs_offer_page):
        page = DogPage(title="Test Dog", slug="test-dog", facebook_album_id="album1")
        needs_offer_page.add_child(instance=page)
        self.mock_update.assert_called_once_with(new=True)

    def test_is_new_false_for_existing_page(self, needs_offer_page):
        page = DogPageFactory(parent=needs_offer_page, facebook_album_id="album1")
        self.mock_update.reset_mock()
        page.title = "Updated title"
        page.save()
        self.mock_update.assert_called_once_with(new=False)

    def test_skips_api_when_no_album_id(self, needs_offer_page):
        DogPageFactory(parent=needs_offer_page, facebook_album_id=None)
        self.mock_update.assert_not_called()

    def test_skips_api_when_rate_limited(self, needs_offer_page, albums_obj):
        albums_obj.set_rate_limit()
        DogPage(title="T", slug="t", facebook_album_id="album1")
        page = DogPage(title="T", slug="t-dog", facebook_album_id="album1")
        needs_offer_page.add_child(instance=page)
        self.mock_update.assert_not_called()

    def test_skips_api_for_existing_page_if_recently_fetched(self, needs_offer_page, albums_obj, freezer):
        freezer.move_to("2024-06-01T12:00:00+00:00")
        albums_obj.update_album("album1", {
            "name": "dog 1",
            "last_fetched": "2024-06-01T12:00:00+00:00",
        })
        page = DogPageFactory(parent=needs_offer_page, facebook_album_id="album1")
        self.mock_update.reset_mock()
        freezer.tick(timedelta(minutes=30))
        page.title = "Updated"
        page.save()
        self.mock_update.assert_not_called()

    def test_calls_api_for_existing_page_if_not_recently_fetched(self, needs_offer_page, albums_obj, freezer):
        freezer.move_to("2024-06-01T12:00:00+00:00")
        albums_obj.update_album("album1", {
            "name": "dog 1",
            "last_fetched": "2024-06-01T10:00:00+00:00",
        })
        page = DogPageFactory(parent=needs_offer_page, facebook_album_id="album1")
        self.mock_update.reset_mock()
        page.title = "Updated"
        page.save()
        self.mock_update.assert_called_once_with(new=False)

    def test_calls_api_for_new_page_even_if_recently_fetched(self, needs_offer_page, albums_obj, freezer):
        """New pages always fetch, regardless of last_fetched."""
        freezer.move_to("2024-06-01T12:00:00+00:00")
        albums_obj.update_album("album1", {
            "name": "dog 1",
            "last_fetched": "2024-06-01T12:00:00+00:00",
        })
        page = DogPage(title="New Dog", slug="new-dog", facebook_album_id="album1")
        needs_offer_page.add_child(instance=page)
        self.mock_update.assert_called_once_with(new=True)


# ---------------------------------------------------------------------------
# FacebookTokenManager
# ---------------------------------------------------------------------------

class TestFacebookTokenManager:

    def test_reads_token_from_file(self, tmp_path, settings):
        settings.FB_ACCESS_TOKEN_PATH = tmp_path / ".fb_access_token"
        settings.FB_ACCESS_TOKEN_PATH.write_text("stored_token")
        manager = FacebookTokenManager()
        assert manager.get_current_access_token() == "stored_token"

    def test_seeds_from_setting_when_no_file(self, tmp_path, settings):
        settings.FB_ACCESS_TOKEN_PATH = tmp_path / ".fb_access_token"
        settings.FB_ACCESS_TOKEN = "initial_token"
        manager = FacebookTokenManager()
        token = manager.get_current_access_token()
        assert token == "initial_token"
        assert settings.FB_ACCESS_TOKEN_PATH.read_text() == "initial_token"

    def test_get_token_status_ok(self):
        future = (timezone.now() + timedelta(days=30)).timestamp()
        with patch("dogs.models.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"data": {"expires_at": future}}
            manager = FacebookTokenManager()
            assert manager.get_token_status("token") == "ok"

    def test_get_token_status_expires_soon(self):
        soon = (timezone.now() + timedelta(hours=12)).timestamp()
        with patch("dogs.models.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"data": {"expires_at": soon}}
            manager = FacebookTokenManager()
            assert manager.get_token_status("token") == "expires_soon"

    def test_get_token_status_expired(self):
        with patch("dogs.models.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "error": {"message": "Session has expired at unix time 12345"}
            }
            manager = FacebookTokenManager()
            assert manager.get_token_status("token") == "expired"

    def test_get_token_status_expired_by_timestamp(self):
        """A past expires_at should return 'expired' even without an API-level error."""
        past = (timezone.now() - timedelta(hours=1)).timestamp()
        with patch("dogs.models.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"data": {"expires_at": past}}
            manager = FacebookTokenManager()
            assert manager.get_token_status("token") == "expired"

    def test_get_token_status_rate_limited(self, albums_obj):
        with patch("dogs.models.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "error": {"message": "Request limit reached"}
            }
            manager = FacebookTokenManager()
            status = manager.get_token_status("token")
            assert status == "rate_limited"
            albums_obj.refresh_from_db()
            assert albums_obj.is_rate_limited
