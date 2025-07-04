from datetime import datetime, timedelta
from io import BytesIO
import logging
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


IDS_TO_IGNORE = [
    "489076346765992",  # Mobile uploads
    "489076353432658",  # Timeline photos
    "489076360099324",  # Cover photos
    "489076350099325",  # Profile pictures
    "478527842488598",  # All dogs for adoption/foster/ sponsor
    "1456923637982342",  # In Loving Memory
    "1022503768091000",  # Sponsor a Hound Programme
    "1147766635564712",  # Vega, Dina & Balto - their journey
    "819257798415599",  # Pal - a remarkable love story -saved from the brink of death
    "795739000767479",  # Nino - in memoriam see Nino's Tale for his story
    "177583412583044",  # Pacita The Pod who Started it All!
    "1883457118662323",  # Puma/Norah
    "668225005517791", # Peeps
    "920246696982286", # all dogs in foster in UK
    "342935776047806", # happily homed
]


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
    #         "updated_time": ""
    #         }
    #     },
    # }
    albums = models.JSONField()
    previous_albums = models.JSONField(default=dict) # backup 
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
        self.previous_albums = self.albums
        self.albums = all_album_data
        self.date_updated = timezone.now()
        self.save()


class FacebookAlbumTracker:

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
            # make sure the token is up to date
            token_status = self.get_token_status(token)
            if token_status == "expired":
                # raise exception; generate a new token
                # at https://developers.facebook.com/tools/explorer/
                # try deleting path and getting token again, in case we're
                # added a new starting short-lived token
                settings.FB_ACCESS_TOKEN_PATH.unlink()
                token = self.get_current_access_token()
                token_status = self.get_token_status(token)
                if token_status == "expired":
                    # definitely expired; raise exception
                    raise Exception("Access token session has expired.")
            elif token_status == "expires_soon":
                # extend token and write it to file
                token = self.extend_token()
                settings.FB_ACCESS_TOKEN_PATH.write_text(token)
            # setup api with  token
            self._api = GraphAPI(access_token=token)
        return self._api
                               
    def get_all_albums(self):
        """
        Get all albums for existing DogPages
        """
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

    def get_token_status(self, token):
        # check expiry; "soon" means it expired in the next day
        url = (
            f"https://graph.facebook.com/debug_token?input_token={token}"
            f"&access_token={token}"
        )
        token_resp = requests.get(url).json()
        # error if rate limited
        if token_resp.get("error"):
            error_msg = token_resp["error"].get("message", "")
            if "Session has expired" in error_msg:
                return "expired"    
            elif "limit" in error_msg:
                self.albums_obj.set_rate_limit()
                return "rate_limited"
            else:
                return f"Error: {error_msg}"

        expiry = datetime.fromtimestamp(token_resp["data"]["expires_at"])
        if expiry < datetime.now() + timedelta(days=1):
            return "expires_soon"
    
        # session_expiry = datetime.fromtimestamp(token_resp["data"]["data_access_expires_at"])
        # if session_expiry < datetime.now() + timedelta(days=7):
        #     return "session_expires_soon"

        return "ok"
            
    def extend_token(self):
        # Extend the expiration time of a valid OAuth access token.
        return self.api.extend_access_token(self.app_id, self.app_secret)["access_token"]

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
    
    def get_album_metadata(self, album_id):
        return self.api.get_object(album_id, fields="name,link,description,updated_time,count")

    def get_album_images(self, album_id):
        # get images (max 50) for album
        url = f"https://graph.facebook.com/v18.0/{album_id}/photos/?fields=images&access_token={self.api.access_token}"
        resp_json = requests.get(url).json()
        while True:
            yield from resp_json["data"]
            if 'next' not in resp_json.get('paging', {}):
                break
            resp_json = requests.get(resp_json["paging"]["next"]).json()

    def create_gallery_image(self, page, collection, image_id, image_url):
        # create the gallery image
        # image id is the facebook image id
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
            return Collection.objects.get(name=collection_name )
        except Collection.DoesNotExist:
            root_collection = Collection.get_first_root_node()
            return root_collection.add_child(name=collection_name)
        
    def get_album_data(self, album_id, album_metadata=None, force_update=False):
        # When we fetch all new album data, there may be data for dogs that we don't
        # have a page for yet. Those will be created manually, so we just want to 
        # retrieve the data for them, not to create collection or gallery images.
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
            and self.albums_obj.get_album(album_id).get("updated_time") == album_metadata.get("updated_time")
        ):
            return self.albums_obj.get_album(album_id)
        
        if album_metadata["id"] in IDS_TO_IGNORE:
            logger.info("Ignoring album '%s'", album_metadata["name"])
            return

        del album_metadata["id"]
        
        # Get photo data and urls for album photos
        album_metadata["images"] = []

        for photo in self.get_album_images(album_id):
            images = photo.pop("images")
            photo["image_url"] = images[0]["source"]
            album_metadata["images"].append(photo)

            if page and (photo["id"] not in page_image_ids):
                self.create_gallery_image(page, collection, photo["id"], photo["image_url"])
                
        return album_metadata

    def fetch_all(self, force_update=False):
        """Retrieve all album data from facebook"""
        # get all albums for page
        all_current_albums = list(self.api.get_all_connections(
            id=settings.FB_PAGE_ID, connection_name="albums", 
            fields="name,link,description,updated_time,count",
        ))

        total = len(all_current_albums)
        albums_data = {}
        for i, album_metadata in enumerate(all_current_albums, start=1):
            album_id = album_metadata["id"]
            logger.info("Fetching album %d of %d (%s)", i, total, album_id)
            album_data = self.get_album_data(album_id, force_update=force_update)
            if album_data is not None:      
                albums_data[album_id] = album_data
        return albums_data

    def update_all(self, new_data=None, force_update=False):  
        new_data = new_data or self.fetch_all(force_update=force_update)
        changes = self.report_changes(new_data)
        new_pages = self.create_new_pages(changes["added"])
        remove_pages = self.remove_pages(changes["removed"])
        failed_to_delete = set(changes["removed"]) - remove_pages
        changes["added"] = new_pages
        changes["failed_to_delete"] = failed_to_delete
        self.albums_obj.update_all(new_data)
        logger.info("All album data updated")
        return changes

    def create_new_pages(self, new_fb_albums):
        # For new albums, we assume the dog is in Spain and needs offer
        needs_offer_page = DogStatusPage.objects.get(title__iexact="Needs Offer")

        new_pages = {}
        for album_id, album_name in new_fb_albums.items():
            # FB album title is usually in the format "<Name> - in Spain, needs offer"
            # Split on - and take the first element. If that doesn't work, try splitting
            # on commas.
            dog_name = album_name.strip().split("-")[0].strip().title()
            if len(dog_name) == 1:
                dog_name = album_name.strip().split(",")[0].strip().title()
            dog_page = DogPage(title=dog_name, location="Spain", facebook_album_id=album_id)
            new_pages[album_id] = {"facebook_album_name": album_name, "page_title": dog_name}
            needs_offer_page.add_child(instance=dog_page)

        return new_pages

    def remove_pages(self, removed_fb_albums):
        deleted = set()
        for album_id in removed_fb_albums:
            # make sure it doesn't exist, or it's ignored
            can_delete = album_id in IDS_TO_IGNORE
            if not can_delete:
                try:
                    self.get_album_metadata(album_id)
                except GraphAPIError:
                    can_delete = True
            if can_delete:
                DogPage.objects.get(facebook_album_id=album_id).delete()
                deleted.add(album_id)
        return deleted

    def update_albums(self, album_ids, force_update=False):
        for i, album_id in enumerate(album_ids, start=1):
            logger.info("Updating album %d of %d", i, len(album_ids))
            self.create_or_update_album(album_id, force_update=force_update)

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
            # Only report changes to name (may require moving to different status page)
            # description and images are updated automatically
            changes["changed"] = {
                album_id: f"{new_data[album_id]['name']} (previously {saved_data[album_id]['name']})"
                for album_id in same_albums
                if new_data[album_id]["name"] != saved_data[album_id]["name"]
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
        super().save(*args, **kwargs)
        albums_obj = FacebookAlbums.instance()
        if self.facebook_album_id and not albums_obj.is_rate_limited:
            new = False if not self.id else True
            try:
                logger.info("Checking fb info for album id %s, dog %s", self.facebook_album_id, self.title)
                self.update_facebook_info(new=new)
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
