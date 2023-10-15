from datetime import datetime, timedelta
import logging
import requests

from django import forms
from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from facebook import GraphAPI, GraphAPIError

from modelcluster.fields import ParentalKey
from wagtail.models import Orderable, Page
from wagtail.fields import RichTextField
from wagtail.admin.forms import WagtailAdminPageForm
from wagtail.admin.panels import FieldPanel, InlinePanel, HelpPanel, Panel
from wagtail.snippets.models import register_snippet

from wagtail_json_widget.widgets import JSONEditorWidget


logger = logging.getLogger(__name__)


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

        # BreadPage objects (get_breads) are passed through pagination
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
    #         "updated_time": ""
    #         }
    #     },
    # }
    albums = models.JSONField()
    date_updated = models.DateTimeField(default=timezone.now)
    rate_limited_at = models.DateTimeField(null=True)

    @classmethod
    def instance(cls):
        if cls.objects.exists():
            return cls.objects.last()
        return cls.objects.create(albums={})

    @property
    def is_rate_limited(self):
        is_limited = self.rate_limited_at is not None
        if not is_limited:
            return False
        
        is_limited = timezone.now() <= self.rate_limited_at + timedelta(minutes=60)
        if not is_limited:
            self.clear_rate_limit()

        return is_limited 

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


class FacebookAlbumTracker:

    albums_to_ignore = [
        "Cover photos", "Profile pictures", "Timeline photos", "Mobile uploads"
    ]


    def __init__(self):
        self._api = None
        self.app_id = settings.FB_APP_ID # Obtained from https://developers.facebook.com/
        self.app_secret = settings.FB_APP_SECRET # Obtained from https://developers.facebook.com/
        self.albums_obj = FacebookAlbums.instance()
    
    @property
    def api(self):
        """Setup the fb graph api"""
        if self._api is None:
            # read the current access token
            token = self.get_current_access_token()
            self._api = GraphAPI(access_token=token) 
            # make sure the token is up to date
            if self.token_expires_soon(token):
                # generate new token and write it to file
                token = self.generate_new_token()
                settings.FB_ACCESS_TOKEN_PATH.write_text(token)
                # setup api with new token
                self._api = GraphAPI(access_token=token)
        return self._api

    def get_all_albums(self):
        """
        Get all albums for existing DogPages except those with custom album data
        """
        album_ids = DogPage.objects.filter(
            custom_album_data__isnull=True
        ).values_list("facebook_album_id", flat=True)
        # filter None and empty strings
        album_ids = [albid for albid in album_ids if albid]
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

    def get_current_access_token(self):
        token_path = settings.FB_ACCESS_TOKEN_PATH
        if not token_path.exists():
            # if the path doesn't already exist, it's the first time we've
            # accessed it, use the access token setting provided and
            # write that to file. The access token setting won't be used
            # again
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(settings.FB_ACCESS_TOKEN)
        token = token_path.read_text()
        return token

    def token_expires_soon(self, token):
        # check expiry; "soon" means it expired in the next day
        url = (
            f"https://graph.facebook.com/debug_token?input_token={token}"
            f"&access_token={token}"
        )
        token_resp = requests.get(url).json()
        # error if rate limited
        if token_resp.get("error"):
            self.albums_obj.set_rate_limit()
            return False
        expiry = datetime.fromtimestamp(token_resp["data"]["expires_at"])
        return expiry < datetime.now() + timedelta(days=1)
            
    def generate_new_token(self):
        # Extend the expiration time of a valid OAuth access token.
        return self.api.extend_access_token(self.app_id, self.app_secret)["access_token"]

    def create_or_update_album(self, album_id):
        metadata = self.get_album_metadata(album_id)
        if self.albums_obj.get_album(album_id).get("updated_time") != metadata.get("updated_time"):
            logger.info("Updating album %s", album_id)
            album_data = self.get_album_data(album_id, metadata)
            if album_data:
                self.albums_obj.update_album(album_id, album_data)
        else:
            logger.info("Album %s is up to date", album_id)
    
    def get_album_metadata(self, album_id):
        return self.api.get_object(album_id, fields="name,link,description,updated_time,count")

    def get_album_data(self, album_id, album_metadata=None, force_update=False):
        album_data = album_metadata or self.get_album_metadata(album_id)
        if (
            not force_update 
            and self.albums_obj.get_album(album_id).get("updated_time") == album_data.get("updated_time")
        ):
            return self.albums_obj.get_album(album_id)
        
        if album_data["name"] in self.albums_to_ignore:
            logger.info("Ignoring album '%s'", album_data["name"])
            return

        del album_data["id"]
        
        # Get photo data and urls for album photos
        photos = self.api.get_object(id=album_id, fields="photos").get("photos")
        
        if not photos:
            return None
        
        album_data["images"] = []

        def _add_images(photos):
            for photo in photos["data"]:
                photo = self.api.get_object(id=photo["id"], fields="alt_text,alt_text_custom,name,link,images")
                images = photo.pop("images")
                photo["image_url"] = images[0]["source"]
                album_data["images"].append(photo)

        _add_images(photos)
        while photos["paging"].get("next"):
            photos =requests.get(photos["paging"]["next"]).json()
            _add_images(photos)
        
        return album_data

    def fetch_all(self, force_update=False):
        """Retrieve and all album data from facebook"""
        # get all albums for page
        # albums = self.api.get_connections(
        #     id=settings.FB_PAGE_ID, connection_name="albums", 
        #     fields="name,link,description,updated_time,count"
        # )["data"]

        # get all albums for current dogs
        albums = self.get_all_albums().values()
        total = len(albums)
        albums_data = {}
        for i, album_metadata in enumerate(albums, start=1):
            album_id = album_metadata["id"]
            logger.info("Fetching album %d of %d", i, total)
            album_data = self.get_album_data(album_metadata["id"], album_metadata, force_update)
            if album_data is not None:      
                albums_data[album_id] = album_data
        return albums_data

    def update_all(self, new_data=None, force_update=False):
        new_data = new_data or self.fetch_all(force_update)
        self.report_changes(new_data)
        self.albums_obj.update_all(new_data)
        logger.info("All album data updated")

    def report_changes(self, new_data):
        saved_data = self.albums_obj.albums
        changes = {"added": {}, "removed": {}, "changed": {}}
        if new_data != saved_data:
            # new items
            new_albums = set(new_data) - set(saved_data)
            removed_albums = set(saved_data) - set(new_data)

            changes["added"] = {
                album_id: new_data[album_id]["name"] for album_id in new_albums
            }
            changes["removed"] = {
                album_id: saved_data[album_id]["name"] for album_id in removed_albums
            }
            
            same_albums = set(new_data) & set(saved_data) 
            changes["changed"] = {
                album_id: new_data[album_id]["name"] for album_id in same_albums
                if new_data[album_id]["updated_time"] != saved_data[album_id]["updated_time"]
            }
        
        changes["custom_albums"] = {
            f"{page.title} ({page.get_parent().title})": page.custom_album_data
            for page in DogPage.objects.filter(custom_album_data__isnull=False)
        }

        return changes


class DogPageForm(WagtailAdminPageForm):
    custom_album_data = forms.JSONField(
        widget=JSONEditorWidget, required=False,
        help_text=(
            "Custom album data to use if FB album can't be retrieved."
            "Format: {'link': '<link to fb album>', 'images': [{'image_url': <url>}]}"
        )
    )


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

    custom_album_data = models.JSONField(
        null=True, blank=True,
        help_text=(
            "Custom album data to use if FB album can't be retrieved."
            "Format: {'link': '<link to fb album>', 'images': [{'image_url': <url>}]}"
        )
    )
    cover_image_index = models.PositiveIntegerField(default=0)

    base_form_class = DogPageForm

    
    content_panels = Page.content_panels + [
        RateLimitedPanel(),
        FieldPanel('date_posted'),
        FieldPanel('location'),
        FieldPanel('description'),
        FBDescPanel(),
        FieldPanel('caption'),
        FBCaptionPanel(),
        FieldPanel('facebook_album_id'),
        FieldPanel('custom_album_data'),
        FieldPanel('cover_image_index'),
    ]

    subpage_types = []
    parent_page_types = ["DogStatusPage"]

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

    def update_facebook_info(self):
        if self.custom_album_data:
            logger.info("Custom album data provided, nothing to update")
            return
        tracker = FacebookAlbumTracker()
        tracker.create_or_update_album(self.facebook_album_id)

    @property
    def album_info(self):
        if not self.id:
            return {}
        if self._album_info is None:
            if self.custom_album_data:
                return self.custom_album_data
            albums_obj = FacebookAlbums.instance()
            self._album_info = albums_obj.get_album(self.facebook_album_id)
        return self._album_info

    def images(self):
        return self.album_info.get("images")

    def cover_image(self):
        if self.images():
            index = self.cover_image_index if len(self.images()) >= self.cover_image_index + 1 else 0
            return self.album_info["images"][index]

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

    def save(self, *args, **kwargs):
        albums_obj = FacebookAlbums.instance()
        if self.facebook_album_id and not albums_obj.is_rate_limited:
            try:
                logger.info("Checking fb info for album id %s, dog %s", self.facebook_album_id, self.title)
                self.update_facebook_info()
            except GraphAPIError as e:
                logger.error(e)
                albums_obj = FacebookAlbums.instance()
                albums_obj.set_rate_limit()
        super().save(*args, **kwargs)
