import random
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from shortuuid.django_fields import ShortUUIDField

from modelcluster.fields import ParentalKey
from wagtail.models.media import Collection
from wagtail.models import Orderable, Page
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel, InlinePanel, HelpPanel, Panel, MultipleChooserPanel
from wagtail.images.models import Image


PAGE_TYPE_COSTS = {
    "single": 5,
    "double": 10,
    "single_with_facing": 10,
    "photo": 5,
}
PAGE_TYPE_PAGE_COUNTS = {
    "single": 1,
    "double": 2,
    "single_with_facing": 2,
    "photo": 1,
}


def image_upload_path(instance, filename):
        # file will be uploaded to MEDIA_ROOT/recipes/<reference>/<filename>
        return f"recipes/{instance.reference}/{filename}"


def validate_image_size(image, width=None, height=None):
    error = False
    # limit to 10Mb
    if image.size > 10_000_000:
        raise ValidationError(f"Exceeds max upload size (max 10Mb, {image.size/1_000_000} submitted).")
    if width is not None and image.width < width:
        error = True
    if height is not None and image.height < height:
        error = True
    if error:
        raise ValidationError(
            [f'Size should be at least {width} x {height} pixels ({image.width} x {image.height} submitted).']
        )


def validate_photo(image):
    return validate_image_size(image, width=1500, height=2100)


def validate_profile_image(image):
    return validate_image_size(image, width=710, height=520)


def get_random_code():
    return random.randint(1000, 9999)


class RecipeBookSubmission(models.Model):

    page_types = (
        ("single", "Single recipe page"),
        ("double", "Double recipe page"),
        ("single_with_facing", "Single page recipe with full page facing photo"),
        ("photo", "Photo page only")
    )
    # fields that apply to all page types
    reference = ShortUUIDField(
        primary_key=True,
        editable = False
    )

    name = models.CharField(help_text="Your name")
    email = models.EmailField(help_text="Your email; we will send a copy of your submission to this address")

    page_type = models.CharField(choices=page_types)

    # recipe fields, applies to all except photo page types
    title = models.CharField(blank=True, max_length=100, help_text="Title of recipe. Maximum 100 characters.")
    category = models.CharField(choices=[("dog", "Dog recipes"), ("human", "Human recipes")], blank=True)
    preparation_time = models.CharField(help_text="Preparation time (please include units)", blank=True, max_length=50)
    cook_time = models.CharField(help_text="Cook time (please include units)", blank=True, max_length=50)

    servings = models.CharField(help_text="How many servings does the recipe make? e.g. serves 4, makes 16", blank=True,  max_length=50)
    ingredients = models.TextField(help_text="List ingredients as they should appear in the recipe (include subheadings if you want)", blank=True, max_length=500)
    method = models.TextField(help_text="Recipe instructions", blank=True)

    submitted_by = models.CharField(
        help_text=(
            "Name(s) for the 'Submitted by' section in the recipe. This can be your full name, your first "
            "name, your dog's name - however you want it to appear e.g. 'Becky & Nala'. This will appear "
            "next to your profile image."
        ), 
        blank=True,
        max_length=100,
    )
    profile_image = models.ImageField(
        null=True,
        blank=True,
        upload_to=image_upload_path,
        validators=[FileExtensionValidator(['jpg', 'jpeg']), validate_profile_image],
        help_text="In order to print at good quality, we require photos at min 300dpi, width 710px, height 520px."

    )
    profile_caption = models.TextField(
        help_text=(
            "Optional caption to go with your profile image. E.g. Say something about the recipe, about why you "
            "chose it, or about your dog(s), when they were adopted etc."
        ), 
        blank=True,
        max_length=300,
    )

    # Applies to double, single_with_facing and photo pages only
    photo = models.ImageField(
        null=True,
        blank=True,
        upload_to=image_upload_path,
        validators=[FileExtensionValidator(['jpg', 'jpeg']), validate_photo],
        help_text=(
            "Please upload the highest quality photo you can (up to 10Mb). "
            "To print a full borderless page at 300dpi, photos need to be min width 2490px, min height 3510px. "
            "You can upload a photo smaller than this (min width 1500px, min height 2100px) "
            "but they may need to be printed smaller than full page."
        )
    )
    photo_title = models.CharField(
        max_length=50, 
        null=True,
        blank=True,
        help_text="Title for photo (e.g. dog's name)"
    )
    # Applies to double and photo pages only
    photo_caption = models.CharField(
         null=True, blank=True, max_length=100, 
         help_text="Optional: A short caption to print under photo title"
    )

    # Admin and payments, applies to all
    date_submitted = models.DateTimeField(default=timezone.now)
    paid = models.BooleanField(default=False)
    date_paid = models.DateTimeField(null=True, blank=True)
    processing = models.BooleanField(default=False)
    complete = models.BooleanField(default=False)

    code = models.PositiveIntegerField(default=get_random_code)

    class Meta:
        ordering = ("-date_submitted",)

    def __str__(self):
        title_str = ""
        if self.title:
            title_str = f"; recipe '{self.title}'"
        return f"Submission from {self.name}{title_str} ({self.reference})"
    
    @property
    def cost(self):
        return PAGE_TYPE_COSTS[self.page_type]

    def status(self):
        if self.paid:
            if self.complete:
                return "Paid and complete"
            elif self.processing:
                return "Paid, processing submission"
            else:
                 return "Paid"
        else:
            return "Payment pending"

    def status_colour(self):
        if self.paid:
            if self.complete:
                return "success"
            elif self.processing:
                return "primary"
            else:
                return "info"
        return "danger"

    def page_type_verbose(self):
         return dict(self.page_types)[self.page_type]
    page_type_verbose.short_description = "Page type"

    def formatted_cost(self):
         return f"£{self.cost:.2f}"
    formatted_cost.short_description = "Cost"

    def get_absolute_url(self):
        return reverse("fundraising:recipe_book_contribution_detail", kwargs={"pk": self.reference})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.paid and not self.date_paid:
            self.date_paid = timezone.now()
        super().save(*args, **kwargs)


class Auction(Page):

    body = RichTextField(blank=True, help_text="Optional content to display in the body of the Auction page.")
    
    open_at = models.DateTimeField()
    close_at = models.DateTimeField()

    content_panels = Page.content_panels + [
        FieldPanel('body'),
        FieldPanel('open_at'),
        FieldPanel('close_at'),
    ]

    subpage_types = ["AuctionItem"]
    parent_page_types = ["home.HomePage"]

    paginate_by = 20


class AuctionCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        verbose_name_plural = "Auction categories"

    def __str__(self) -> str:
        return self.name


class AuctionItemPhoto(Orderable):
    page = ParentalKey("AuctionItem", on_delete=models.CASCADE, related_name='photos')
    image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.CASCADE, related_name='+'
    )
    caption = models.CharField(blank=True, max_length=250)

    panels = [
        FieldPanel('image'),
        FieldPanel('caption'),
    ]


class AuctionItem(Page):
    parent_page_types = ["Auction"]

    category = models.ForeignKey(AuctionCategory, on_delete=models.PROTECT)
    description = RichTextField(blank=True, help_text="Optional description of item.")

    donor = models.CharField(max_length=255, help_text="Name of person who donated this item")
    donor_email = models.CharField(max_length=255, help_text="Email address of donor")
    
    starting_bid = models.FloatField()
    postage = models.FloatField(default=0)

    content_panels = Page.content_panels + [
        FieldPanel("category"),
        FieldPanel("description"),
        FieldPanel("donor"),
        FieldPanel("donor_email"),
        FieldPanel("starting_bid"),
        FieldPanel("postage"),
        MultipleChooserPanel(
            'photos',
            label="Photos",
            chooser_field_name="image",
        )
    ]

    def current_winning_bid(self):
        ...


class Bid(models.Model):
    auction_item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name="bids")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.FloatField()
    notify = models.BooleanField(default=True)
