from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from modelcluster.fields import ParentalKey
from wagtail.models import Orderable, Page
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel, InlinePanel, HelpPanel, MultiFieldPanel, MultipleChooserPanel


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
        paginator = Paginator(self.get_dogs(), 12)
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
    

class DogPageGalleryImage(Orderable):
    """
    Example related image
    """
    page = ParentalKey("DogPage", on_delete=models.CASCADE, related_name='gallery_images')
    image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.CASCADE, related_name='+'
    )
    caption = models.CharField(blank=True, max_length=250)

    panels = [
        FieldPanel('image'),
        FieldPanel('caption'),
    ]


class DogPage(Page):

    date_posted = models.DateField(default=timezone.now)
    location = models.CharField(null=True, blank=True, max_length=255)
    description = RichTextField(blank=True)
    facebook_url = models.URLField(null=True, blank=True, help_text="Link to Facebook album page for this dog")

    content_panels = Page.content_panels + [
        FieldPanel('date_posted'),
        FieldPanel('location'),
        FieldPanel('description'),
        FieldPanel('facebook_url'),
        MultipleChooserPanel(
            'gallery_images',
            label="Images",
            chooser_field_name="image",
            help_text=mark_safe(
                "Select up to 6 images to display on the page. The first image will be used "
                "as the banner image and preview image on the category list page.<br/><br/>"
                "Use the arrows on the right of the images to change order.</br/><br/>"
                "If you have multiple images to upload, you can upload them all at "
                "once by going to Images in the main menu and return to this page to select them."
            ),
            max_num=6
        )
    ]

    subpage_types = []
    parent_page_types = ["DogStatusPage"]

    def image(self):
        if self.gallery_images.exists():
            return self.gallery_images.first().image

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

