from datetime import datetime, timedelta
from io import BytesIO
import logging
import re
import requests

from django import forms
from django.conf import settings
from django.core.files.images import ImageFile
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from facebook import GraphAPI, GraphAPIError

from modelcluster.fields import ParentalKey
from wagtail.models.media import Collection
from wagtail.models import Orderable, Page
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel, InlinePanel, HelpPanel, Panel
from wagtail.images.models import Image


logger = logging.getLogger(__name__)

FOSTER_RE = re.compile(r'\bfoster', re.IGNORECASE)
HAPPILY_HOMED_RE = re.compile(r'\bhappily\s+homed\b', re.IGNORECASE)

# Ordered: first match wins
STATUS_ROUTING = [
    (FOSTER_RE, "In foster"),
    (HAPPILY_HOMED_RE, "Happily homed"),
]

RECENTLY_FETCHED_THRESHOLD_HOURS = 1


def get_target_status_title(album_title):
    for pattern, status_title in STATUS_ROUTING:
        if pattern.search(album_title):
            return status_title
    return None



class DogIndexPageStatuses(Orderable):

    page = ParentalKey("DogsIndexPage", related_name="dog_status_pages")
    status_page = models.ForeignKey(
        "DogStatusPage",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Dog status category"
    )

    panels = [FieldPanel("status_page")]


class DogsIndexPage(Page):

    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Header image",
    )
    body = RichTextField(blank=True)
    parent_page_types = ["home.HomePage"]
    subpage_types = ["DogStatusPage"]

    content_panels = Page.content_panels + [
        HelpPanel(
            """This is the index page for all dogs. It will display links to each of the
            chosen dog status categories.<br>
            A status can be hidden by removing it from this page."""
        ),
        FieldPanel("image"),
        FieldPanel('body'),
        InlinePanel(
            "dog_status_pages", label="Displayed statuses",
            help_text=mark_safe("""
            Add Dog Status pages as child pages of this page.<br/>
            Then add each Dog Status page that you want to be visible on this index page
            (in the order you want them to display).<br/>
            Note that only live Dog Status pages will be visible."
            """)
        )
    ]

    # Allows child objects (i.e. DogStatusPage objects) to be accessible via the
    # template. We use this on the HomePage to display child items of featured
    # content
    def status_pages(self):
        return [page.status_page for page in self.dog_status_pages.all() if page.status_page.live]


class DogStatusPage(Page):

    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Header image",
    )
    short_description = models.CharField(
        max_length=255, null=True, blank=True,
        help_text="A one-line description of this status"
    )

    intro = RichTextField(blank=True)

    content_panels = Page.content_panels + [
        HelpPanel(
            mark_safe(
                """
                This page will show all dogs with the selected status.\n
                Create a child page for each dog that has this status (you can 
                move them later if their status changes.)
                """
            )
        ),
        FieldPanel("image"),
        FieldPanel('short_description'),
        FieldPanel('intro'),
    ]

    parent_page_types = ["DogsIndexPage"]
    subpage_types = ["DogPage"]

    # Returns a queryset of DogPage objects that are live, that are direct
    # descendants of this index page with most recent first
    def get_dogs(self):
        return (
            DogPage.objects.live().descendant_of(self).order_by("-date_posted")
        )

    # Allows child objects (e.g. DogPage objects) to be accessible via the
    # template. We use this on the HomePage to display child items of featured
    # content
    def children(self):
        return self.get_dogs()

    # Pagination for the index page. We use the `django.core.paginator` as any
    # standard Django app would, but the difference here being we have it as a
    # method on the model rather than within a view function
    def paginate(self, request, *args):
        page = request.GET.get("page")
        paginator = Paginator(self.get_dogs(), 20)
        try:
            pages = paginator.page(page)
        except PageNotAnInteger:
            pages = paginator.page(1)
        except EmptyPage:
            pages = paginator.page(paginator.num_pages)
        return pages

    # Returns the above to the get_context method that is used to populate the
    # template
    def get_context(self, request):
        context = super().get_context(request)

        # DogPage objects (get_dogs) are passed through pagination
        dogs = self.paginate(request, self.get_dogs())

        context["dogs"] = dogs

        return context


class FBDescPanel(Panel):

    class BoundPanel(Panel.BoundPanel):

        def render_html(self, parent_context):
            return mark_safe(
                f'''
                    <section class="w-panel">
                    <div class="w-panel__header">
                            <h2 class="w-panel__heading w-panel__heading--label" id="panel-child-content-fbdescription-heading" data-panel-heading="">
                                Facebook Album Description
                            </h2>
                        <div class="w-panel__divider"></div>
                    </div>
                    <div id="panel-child-content-location-content" class="w-panel__content">

                    <div class="w-field__wrapper " data-field-wrapper="">
                        <p>{self.instance.fb_description}</p>
                    </div>
                    </section>
                '''
            )


class FBCaptionPanel(Panel):

    class BoundPanel(Panel.BoundPanel):

        def render_html(self, parent_context):
            return mark_safe(
                f'''
                    <section class="w-panel">
                    <div class="w-panel__header">
                            <h2 class="w-panel__heading w-panel__heading--label" id="panel-child-content-fbdescription-heading" data-panel-heading="">
                                Facebook Album Caption
                            </h2>
                        <div class="w-panel__divider"></div>
                    </div>
                    <div id="panel-child-content-location-content" class="w-panel__content">

                    <div class="w-field__wrapper " data-field-wrapper="">
                        <p>{self.instance.fb_caption}</p>
                    </div>
                    </section>
                '''
            )


class RateLimitedPanel(Panel):

    class BoundPanel(Panel.BoundPanel):

        def render_html(self, parent_context):
            if FacebookAlbums.instance().is_rate_limited:
                return mark_safe(f'''
                    <section class="w-panel">
                    <div class="w-panel__header">
                            <p class="w-panel__heading w-panel__heading--label" id="panel-child-content-fbdescription-heading" data-panel-heading="">
                                "Facebook API is currently rate limited, try updating later"
                            </p>
                        <div class="w-panel__divider"></div>
                    </div>
                    </section>
                ''')
            return ""
        

class FacebookAlbums(models.Model):

    # dict representing current state of albums for page
    # {
    #     "<album_id>": {
    #         "name": "",
    #         "count": 10,
    #         "description": "",
    #         "link": "",
    #         "images": [<list of image urls>],
    #         "updated_time": "",
    #         "last_fetched": "",
    #         }
    #     },
    # }
    albums = models.JSONField()
    # Snapshot of albums at the last acknowledgement. The nightly sync diffs
    # new data against this baseline so that changes are reported until
    # explicitly acknowledged, even if a report email is missed.
    reporting_baseline = models.JSONField(default=dict)
    # Site-level changes that don't show up in the album diff (pages moved
    # between status pages, or pages recreated after manual deletion).
    # Cleared on acknowledge alongside reporting_baseline.
    pending_site_changes = models.JSONField(default=dict)
    date_updated = models.DateTimeField(default=timezone.now)
    rate_limited_at = models.DateTimeField(null=True)

    @classmethod
    def instance(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"albums": {}})
        return obj

    @property
    def is_rate_limited(self):
        if self.rate_limited_at is None:
            return False
        return timezone.now() <= self.rate_limited_at + timedelta(minutes=60)

    def set_rate_limit(self):
        self.rate_limited_at = timezone.now()
        self.save()

    def clear_rate_limit(self):
        self.rate_limited_at = None
        self.save()

    def get_album(self, album_id):
        return self.albums.get(album_id, {})

    def update_album(self, album_id, album_data):
        if self.albums is None:
            self.albums = {}
        self.albums[album_id] = album_data
        self.save()

    def update_all(self, all_album_data):
        self.albums = all_album_data
        self.date_updated = timezone.now()
        self.save()

    def acknowledge(self):
        self.reporting_baseline = self.albums
        self.pending_site_changes = {}
        self.save()

    def album_recently_fetched(self, album_id):
        # Prevents redundant API calls when an admin saves a DogPage shortly
        # after the nightly sync has already fetched fresh data.
        last_fetched_str = self.get_album(album_id).get("last_fetched")
        if not last_fetched_str:
            return False
        last_fetched = datetime.fromisoformat(last_fetched_str)
        delta = timedelta(hours=RECENTLY_FETCHED_THRESHOLD_HOURS)
        return timezone.now() - last_fetched < delta

    def pending_changes(self):
        """Return changes between reporting_baseline and current albums."""
        baseline = self.reporting_baseline
        current = self.albums
        added = {
            album_id: current[album_id]["name"]
            for album_id in set(current) - set(baseline)
        }
        removed = {
            album_id: baseline[album_id]["name"]
            for album_id in set(baseline) - set(current)
        }
        changed = {
            album_id: f"{current[album_id]['name']} (previously {baseline[album_id]['name']})"
            for album_id in set(current) & set(baseline)
            if current[album_id].get("name") != baseline[album_id].get("name")
        }
        site = self.pending_site_changes or {}
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "moved": site.get("moved", {}),
            "recreated": site.get("recreated", {}),
        }


class FacebookTokenManager:

    def __init__(self):
        self.app_id = settings.FB_APP_ID
        self.app_secret = settings.FB_APP_SECRET
        self._albums_obj = None

    @property
    def _albums(self):
        if self._albums_obj is None:
            self._albums_obj = FacebookAlbums.instance()
        return self._albums_obj

    def get_current_access_token(self):
        token_path = settings.FB_ACCESS_TOKEN_PATH
        if not token_path.exists():
            # First run: seed the file from the env var. After this the env var
            # is not consulted again; the file holds the live (extended) token.
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(settings.FB_ACCESS_TOKEN)
        return token_path.read_text()

    def get_token_status(self, token):
        # "expires_soon" means expiry within the next day; the caller should
        # extend the token before it lapses.
        url = (
            f"https://graph.facebook.com/debug_token?input_token={token}"
            f"&access_token={token}"
        )
        token_resp = requests.get(url).json()
        if token_resp.get("error"):
            error_msg = token_resp["error"].get("message", "")
            if "Session has expired" in error_msg:
                return "expired"
            elif "limit" in error_msg:
                self._albums.set_rate_limit()
                return "rate_limited"
            else:
                return f"Error: {error_msg}"

        expiry = datetime.fromtimestamp(token_resp["data"]["expires_at"])
        if expiry < datetime.now() + timedelta(days=1):
            return "expires_soon"

        return "ok"

    def extend_token(self, api):
        return api.extend_access_token(self.app_id, self.app_secret)["access_token"]


class FacebookAlbumTracker:

    def __init__(self):
        self._api = None
        self.token_manager = FacebookTokenManager()
        self.albums_obj = FacebookAlbums.instance()

    @property
    def api(self):
        if self._api is None:
            token = self.token_manager.get_current_access_token()
            token_status = self.token_manager.get_token_status(token)
            if token_status == "expired":
                # The stored token has expired. Delete the file so
                # get_current_access_token() falls back to the short-lived seed
                # token from FB_ACCESS_TOKEN, which may have been refreshed.
                settings.FB_ACCESS_TOKEN_PATH.unlink()
                token = self.token_manager.get_current_access_token()
                token_status = self.token_manager.get_token_status(token)
                if token_status == "expired":
                    raise Exception("Access token session has expired.")
            elif token_status == "expires_soon":
                # Extend before it lapses and persist the new long-lived token.
                self._api = GraphAPI(access_token=token)
                token = self.token_manager.extend_token(self._api)
                settings.FB_ACCESS_TOKEN_PATH.write_text(token)
            self._api = GraphAPI(access_token=token)
        return self._api

    def get_all_albums(self):
        album_ids = DogPage.objects.filter(facebook_album_id__isnull=False).values_list("facebook_album_id", flat=True)
        try:
            return self.api.get_objects(album_ids, fields="name,link,description,updated_time,count")
        except GraphAPIError as e:
            if "limit" in str(e):
                self.albums_obj.set_rate_limit()
                logger.error(e)
            results = {}
            for album_id in album_ids:
                try:
                    results[album_id] = self.api.get_object(album_id, fields="name,link,description,updated_time,count")
                except GraphAPIError:
                    logger.error("Album id %s not found", album_id)
            return results

    def get_album_metadata(self, album_id):
        return self.api.get_object(album_id, fields="name,link,description,updated_time,count")

    def get_album_images(self, album_id):
        url = f"https://graph.facebook.com/v18.0/{album_id}/photos/?fields=images&access_token={self.api.access_token}"
        resp_json = requests.get(url).json()
        while True:
            yield from resp_json["data"]
            if 'next' not in resp_json.get('paging', {}):
                break
            resp_json = requests.get(resp_json["paging"]["next"]).json()

    def create_gallery_image(self, page, collection, image_id, image_url):
        image_resp = requests.get(image_url, allow_redirects=True)
        photo_name = f"{page.slug}_{image_id}"
        image = Image(
            title=photo_name,
            file=ImageFile(BytesIO(image_resp.content), name=f"{photo_name}.jpg"),
            collection=collection,
        )
        image.save()
        DogPageGalleryImage.objects.create(page=page, image=image, fb_image_id=image_id)

    def get_collection(self, page, album_id):
        collection_name = f"{page.slug}_{album_id}"
        try:
            return Collection.objects.get(name=collection_name)
        except Collection.DoesNotExist:
            root_collection = Collection.get_first_root_node()
            return root_collection.add_child(name=collection_name)

    def get_album_data(self, album_id, album_metadata=None, force_update=False):
        # A DogPage may not exist yet for a newly discovered album — in that
        # case we still fetch and cache the album data, but skip gallery image
        # creation (which requires a page). The page is created separately by
        # create_new_pages().
        try:
            page = DogPage.objects.get(facebook_album_id=album_id)
            page_image_ids = page.gallery_images.values_list("fb_image_id", flat=True)
            collection = self.get_collection(page, album_id)
        except DogPage.DoesNotExist:
            page = None
            collection = None
            page_image_ids = []

        album_metadata = album_metadata or self.get_album_metadata(album_id)
        if (
            not force_update
            and page is not None
            and self.albums_obj.get_album(album_id).get("updated_time") == album_metadata.get("updated_time")
        ):
            return self.albums_obj.get_album(album_id)

        if album_metadata["id"] in settings.FB_ALBUM_IDS_TO_IGNORE:
            logger.info("Ignoring album '%s'", album_metadata["name"])
            return

        del album_metadata["id"]

        album_metadata["images"] = []
        for photo in self.get_album_images(album_id):
            images = photo.pop("images")
            photo["image_url"] = images[0]["source"]
            album_metadata["images"].append(photo)

            if page and (photo["id"] not in page_image_ids):
                self.create_gallery_image(page, collection, photo["id"], photo["image_url"])

        album_metadata["last_fetched"] = timezone.now().isoformat()
        return album_metadata

    def create_or_update_album(self, album_id, force_update=False):
        metadata = self.get_album_metadata(album_id)
        if force_update or (
            self.albums_obj.get_album(album_id).get("updated_time") != metadata.get("updated_time")
        ):
            logger.info("Updating album %s", album_id)
            album_data = self.get_album_data(album_id, album_metadata=metadata, force_update=force_update)
            if album_data:
                self.albums_obj.update_album(album_id, album_data)
            logger.info("Album %s updated", album_id)
        else:
            logger.info("Album %s is up to date", album_id)

    def fetch_all(self):
        all_current_albums = list(self.api.get_all_connections(
            id=settings.FB_PAGE_ID, connection_name="albums",
            fields="name,link,description,updated_time,count",
        ))
        total = len(all_current_albums)
        albums_data = {}
        for i, album_metadata in enumerate(all_current_albums, start=1):
            album_id = album_metadata["id"]
            logger.info("Fetching album %d of %d (%s)", i, total, album_id)
            album_data = self.get_album_data(album_id)
            if album_data is not None:
                albums_data[album_id] = album_data
        return albums_data

    def update_all(self, new_data=None):
        new_data = new_data or self.fetch_all()
        changes = self.report_changes(new_data)
        new_pages = self.create_new_pages(changes["added"])

        # Recreate pages for known albums whose DogPage was manually deleted from the site
        existing_page_ids = set(
            DogPage.objects.filter(facebook_album_id__in=new_data.keys())
            .values_list('facebook_album_id', flat=True)
        )
        missing_page_albums = {
            album_id: new_data[album_id]["name"]
            for album_id in new_data
            if album_id not in existing_page_ids
        }
        if missing_page_albums:
            recreated = self.create_new_pages(missing_page_albums)
            new_pages.update(recreated)

        removed = self.remove_pages(changes["removed"])
        failed_to_delete = set(changes["removed"]) - removed

        # Check status-page routing for all pre-existing albums, not just title-changed ones,
        # in case a page was manually moved or its parent was wrong before the delete/recreate.
        created_album_ids = set(changes["added"]) | set(missing_page_albums)
        titles_to_route = {
            album_id: new_data[album_id]["name"]
            for album_id in new_data
            if album_id not in created_album_ids
        }
        moved = self.apply_title_routing(titles_to_route)

        # Accumulate site-level changes (moved pages, recreated pages) so they
        # persist in pending_changes() until the admin acknowledges.
        site_changes = self.albums_obj.pending_site_changes or {}
        if moved:
            existing = site_changes.get("moved", {})
            existing.update(moved)
            site_changes["moved"] = existing
        if missing_page_albums:
            existing = site_changes.get("recreated", {})
            existing.update({
                album_id: info
                for album_id, info in new_pages.items()
                if album_id in missing_page_albums
            })
            site_changes["recreated"] = existing
        self.albums_obj.pending_site_changes = site_changes

        changes["added"] = new_pages
        changes["failed_to_delete"] = failed_to_delete
        changes["moved"] = moved
        self.albums_obj.update_all(new_data)
        has_changes = any([new_pages, changes["removed"], changes["changed"], moved,
                           site_changes.get("recreated")])
        if not has_changes:
            self.albums_obj.acknowledge()
        logger.info("All album data updated")
        return changes

    def create_new_pages(self, new_fb_albums):
        needs_offer_page = DogStatusPage.objects.get(title__iexact="Needs Offer")
        new_pages = {}
        for album_id, album_name in new_fb_albums.items():
            # FB album titles are typically "<Name> - in Spain, needs offer".
            # Split on " - " first; fall back to splitting on "," if that
            # produces a single character (i.e. the title had no " - ").
            dog_name = album_name.strip().split("-")[0].strip().title()
            if len(dog_name) == 1:
                dog_name = album_name.strip().split(",")[0].strip().title()
            status_title = get_target_status_title(album_name)
            if status_title:
                try:
                    parent_page = DogStatusPage.objects.get(title__iexact=status_title)
                except DogStatusPage.DoesNotExist:
                    logger.warning("Status page '%s' not found; defaulting to Needs Offer", status_title)
                    parent_page = needs_offer_page
            else:
                parent_page = needs_offer_page
            dog_page = DogPage(title=dog_name, location="Spain", facebook_album_id=album_id)
            new_pages[album_id] = {"facebook_album_name": album_name, "page_title": dog_name}
            parent_page.add_child(instance=dog_page)
        return new_pages

    def apply_title_routing(self, changed_titles):
        """Move pages whose title now matches a status keyword. Returns {album_id: {from, to}}."""
        moved = {}
        for album_id, new_title in changed_titles.items():
            status_title = get_target_status_title(new_title)
            if not status_title:
                continue
            try:
                dog_page = DogPage.objects.get(facebook_album_id=album_id)
            except DogPage.DoesNotExist:
                continue
            current_parent = dog_page.get_parent().specific
            if isinstance(current_parent, DogStatusPage) and current_parent.title.lower() == status_title.lower():
                continue
            try:
                target_page = DogStatusPage.objects.get(title__iexact=status_title)
            except DogStatusPage.DoesNotExist:
                logger.warning("Status page '%s' not found; skipping move for album %s", status_title, album_id)
                continue
            old_title = current_parent.title
            dog_page.move(target_page, pos="last-child")
            moved[album_id] = {"page_title": dog_page.title, "from": old_title, "to": target_page.title}
            logger.info("Moved page for album %s from '%s' to '%s'", album_id, old_title, target_page.title)
        return moved

    def remove_pages(self, removed_fb_albums):
        deleted = set()
        for album_id in removed_fb_albums:
            # Only delete if the album is genuinely gone from Facebook (raises
            # GraphAPIError) or is in the ignore list. This guards against
            # false removals caused by transient API errors during fetch_all.
            can_delete = album_id in settings.FB_ALBUM_IDS_TO_IGNORE
            if not can_delete:
                try:
                    self.get_album_metadata(album_id)
                except GraphAPIError:
                    can_delete = True
            if can_delete:
                try:
                    DogPage.objects.get(facebook_album_id=album_id).delete()
                    deleted.add(album_id)
                except DogPage.DoesNotExist:
                    pass
        return deleted

    def update_albums(self, album_ids, force_update=False):
        for i, album_id in enumerate(album_ids, start=1):
            logger.info("Updating album %d of %d", i, len(album_ids))
            self.create_or_update_album(album_id, force_update=force_update)

    def report_changes(self, new_data):
        baseline = self.albums_obj.reporting_baseline
        changes = {"added": {}, "removed": {}, "changed": {}}
        if new_data != baseline:
            new_albums = set(new_data) - set(baseline)
            removed_albums = set(baseline) - set(new_data)
            changes["added"] = {
                album_id: new_data[album_id]["name"] for album_id in new_albums
            }
            changes["removed"] = {
                album_id: baseline[album_id]["name"] for album_id in removed_albums
            }
            same_albums = set(new_data) & set(baseline)
            # Only title changes are reported; description and image updates
            # are applied automatically without requiring manual action.
            changes["changed"] = {
                album_id: f"{new_data[album_id]['name']} (previously {baseline[album_id]['name']})"
                for album_id in same_albums
                if new_data[album_id]["name"] != baseline[album_id]["name"]
            }
        return changes


class DogPageGalleryImage(Orderable):
    """
    Related images for DogPage; hidden on admin
    """
    page = ParentalKey("DogPage", on_delete=models.CASCADE, related_name='gallery_images')
    fb_image_id = models.CharField(null=True, blank=True, max_length=255)
    image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.CASCADE, related_name='+'
    )

    class Meta:
        ordering = ("-fb_image_id",)


class DogPage(Page):

    date_posted = models.DateField(default=timezone.now)
    location = models.CharField(null=True, blank=True, max_length=255)
    description = RichTextField(
        blank=True, 
        help_text=(
            "Description to use instead of Facebook album description. Leave blank to use "
            "descripton from album page."
        )
    )
    caption = models.CharField(
        null=True, blank=True, max_length=255,
        help_text=(
            "Short caption to be used on status page. Defaults to first sentence of "
            "facebook album description."
        )
    )
    facebook_album_id = models.CharField(null=True, blank=True)

    cover_image_index = models.PositiveIntegerField(default=0)

    content_panels = Page.content_panels + [
        RateLimitedPanel(),
        FieldPanel('date_posted'),
        FieldPanel('location'),
        FieldPanel('description'),
        FBDescPanel(),
        FieldPanel('caption'),
        FBCaptionPanel(),
        FieldPanel('facebook_album_id'),
        FieldPanel('cover_image_index'),
    ]

    subpage_types = []
    parent_page_types = ["DogStatusPage"]

    paginate_by = 20

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._album_info = None

    def category(self):
       move_url = reverse(
            f"wagtailadmin_pages:move",
            args=[self.id],
        )
       return mark_safe(
          f"{self.get_parent().specific.title} <a class='button button-secondary button-small' href='{move_url}'>Change</a>"
        )
    category.short_description = "Dog Status/Category"

    def page_status(self):
        return mark_safe(f"<span class='w-status w-status--primary'>{self.status_string.title()}</span>")

    def update_facebook_info(self, new=False):
        tracker = FacebookAlbumTracker()
        tracker.create_or_update_album(self.facebook_album_id, force_update=new)

    @property
    def album_info(self):
        if not self.id:
            return {}
        if self._album_info is None:
            albums_obj = FacebookAlbums.instance()
            self._album_info = albums_obj.get_album(self.facebook_album_id)
        return self._album_info
    
    def images(self):
        return self.album_info.get("images")

    def get_gallery_images(self):
        return self.specific.gallery_images.all()

    def cover_image(self):
        gallery_images = self.get_gallery_images()
        if gallery_images.exists():
            index = self.cover_image_index if gallery_images.count() >= self.cover_image_index + 1 else 0
            if index == 0:
                gallery_image = gallery_images.first()
            else:
                gallery_image = list(gallery_images.all())[index]
            return gallery_image.image

    @property
    def fb_description(self):
        return self.album_info.get("description", "")
    
    @property
    def fb_caption(self):
        return self.album_info.get("description", "").split(".")[0]

    @property
    def facebook_url(self):
        return self.album_info.get("link")

    @property
    def is_rate_limited(self):
        return FacebookAlbums.instance().is_rate_limited

    # Pagination for the dog page. We use the `django.core.paginator` as any
    # standard Django app would, but the difference here being we have it as a
    # method on the model rather than within a view function
    def paginate(self, request, gallery_images):
        page = request.GET.get("page")
        paginator = Paginator(gallery_images, self.specific.paginate_by)
        try:
            pages = paginator.page(page)
        except PageNotAnInteger:
            pages = paginator.page(1)
        except EmptyPage:
            pages = paginator.page(paginator.num_pages)
        return pages

    # Returns the above to the get_context method that is used to populate the
    # template
    def get_context(self, request):
        context = super().get_context(request)
        context["gallery_images"] = self.paginate(request, self.get_gallery_images())
        context["paginate_by"] = self.paginate_by
        return context

    def save(self, *args, **kwargs):
        _is_new = not self.pk
        super().save(*args, **kwargs)
        if not self.facebook_album_id:
            return
        albums_obj = FacebookAlbums.instance()
        if albums_obj.is_rate_limited:
            return
        if not _is_new and albums_obj.album_recently_fetched(self.facebook_album_id):
            return
        try:
            logger.info("Checking fb info for album id %s, dog %s", self.facebook_album_id, self.title)
            self.update_facebook_info(new=_is_new)
        except GraphAPIError as e:
            logger.error(e)
            if "Unsupported get request" in str(e):
                raise
            albums_obj = FacebookAlbums.instance()
            albums_obj.set_rate_limit()


@receiver(pre_delete, sender=DogPage, dispatch_uid='dogpage_delete_collection')
def delete_page_collection(sender, instance, using, **kwargs):
    album_tracker = FacebookAlbumTracker()
    collection = album_tracker.get_collection(instance, instance.facebook_album_id)
    collection.delete()
