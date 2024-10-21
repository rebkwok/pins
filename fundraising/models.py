from decimal import Decimal
import random
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings
from django.shortcuts import redirect
from django import forms
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from crispy_forms.bootstrap import PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, Submit, Fieldset, HTML

from shortuuid.django_fields import ShortUUIDField

from modelcluster.models import ClusterableModel
from modelcluster.fields import ParentalKey
from wagtail.models.media import Collection
from wagtail.models import Orderable, Page
from wagtail.fields import RichTextField
from wagtail.admin.mail import send_mail
from wagtail.admin.panels import FieldPanel, InlinePanel, HelpPanel, Panel, MultipleChooserPanel
from wagtail.images.models import Image

from .utils import user_address_choices


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


class AuctionsPage(Page):

    body = RichTextField(blank=True, help_text="Optional content to display in the body of the Auction page.")

    content_panels = Page.content_panels + [
        FieldPanel('body'),
    ]

    subpage_types = ["Auction"]
    parent_page_types = ["home.HomePage"]

    paginate_by = 20

    def auctions(self):
        return Auction.objects.live().descendant_of(self).order_by("-close_at")

from wagtail.search import index


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
    parent_page_types = ["AuctionsPage"]

    paginate_by = 20

    class Meta:
        ordering = ("-close_at",)

    def is_open(self):
        return self.open_at <= timezone.now()
    
    def is_closed(self):
        return self.close_at <= timezone.now()
    
    @classmethod
    def open(cls):
        return cls.objects.filter(
            open_at__lte=timezone.now(), close_at__gte=timezone.bow()
        )
    
    def categories(self):
        categories = {}
        for auction_item in self.get_children().specific().live():
            categories.setdefault(auction_item.category, []).append(auction_item)
        return categories

    def notify_winners_url(self):
        return reverse("fundraising:notify_auction_winners", args=(self.pk,))


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
    subpage_types = []

    category = models.ForeignKey(AuctionCategory, on_delete=models.PROTECT)
    description = RichTextField(blank=True, help_text="Optional description of item.")

    donor = models.CharField(max_length=255, help_text="Name of person who donated this item")
    donor_email = models.CharField(max_length=255, help_text="Email address of donor")
    show_donor = models.BooleanField(default=True, help_text="Display donor's name on item page")
    
    starting_bid = models.DecimalField(max_digits=6, decimal_places=2)
    postage =models.DecimalField(max_digits=6, decimal_places=2, default=0.00)

    content_panels = Page.content_panels + [
        FieldPanel("category"),
        FieldPanel("description"),
        FieldPanel("donor"),
        FieldPanel("donor_email"),
        FieldPanel("show_donor"),
        FieldPanel("starting_bid"),
        FieldPanel("postage"),
        MultipleChooserPanel(
            'photos',
            label="Photos",
            chooser_field_name="image",
        )
    ]

    def get_admin_display_title(self):
        return f"{self.title} ({self.category})"
    
    def image(self):
        if self.photos.exists():
            return self.photos.first().image

    def get_form(self, request, data=None, *, instance=None):
        user = request.user.id if request.user.is_authenticated else None
        return BidForm(data, initial={"auction_item": self.id, "user": user}, instance=instance)

    def serve(self, request, *args, **kwargs):
        request.is_preview = False
        form = None
        if request.user.is_authenticated:
            if request.method == "POST":
                instance = self.bids.filter(id=request.POST.get("id")).first()
                if "delete_bid" in request.POST:
                    amount = instance.amount
                    instance.delete()
                    AuctionItemLog.objects.create(auction_item=self, log=f"User {request.user} ({request.user.id}) deleted bid: £{amount}")
                    messages.success(request, "Your bid was deleted")
                    return redirect(self.get_url())
                else:
                    form = self.get_form(request, request.POST, instance=instance)
                    if form.is_valid():
                        bid = form.save()
                        messages.success(request, "Thank you for your bid! Winners will be notified by email after the auction has closed.")

                        # Email next highest bidder if they have requested notification that their bid has
                        # been exceeded. Don't notify the one lower than that, as they should have been notified
                        # when their bid was first exceeded
                        next_highest = self.active_bids.exclude(id=bid.id).order_by("-amount").first()
                        if (
                            next_highest 
                            and next_highest.notify
                            and next_highest.user != bid.user
                        ):
                            send_mail(
                                "PINS Auction: You have been out-bid!",
                                (
                                    "Your bid on the following PINS auction item is no longer the winning bid:\n"
                                    f"{self.title} ({self.get_parent().title})\n\n"
                                    f"Go to {self.get_full_url(request)} to bid again.\n"
                                ),
                                [next_highest.user.email],
                                settings.DEFAULT_FROM_EMAIL,
                                reply_to=[settings.DEFAULT_ADMIN_EMAIL],
                            )
                        return redirect(self.get_url())
                    else:
                        messages.error(request, "Please correct the errors below")
            else:
                # Does the user already have a bid? If so, use it in the form
                instance = self.active_bids.filter(user=request.user).last()
                form = self.get_form(request, instance=instance)

        context = self.get_context(request, *args, **kwargs, form=form)

        return TemplateResponse(
            request,
            self.get_template(request, *args, **kwargs),
            context,
        )    

    @property
    def active_bids(self):
        return self.bids.filter(withdrawn=False)

    def current_winning_bid(self):
        return self.active_bids.aggregate(models.Max("amount", default=0))["amount__max"]

    @property
    def current_winning_bid_obj(self):
        if self.active_bids.exists():
            return self.active_bids.get(amount=self.current_winning_bid())
    
    def total_due(self):
        if self.active_bids.exists():
            return self.current_winning_bid() + self.postage
        return 0

    def winner(self):
        if self.active_bids.exists():
            return self.current_winning_bid_obj.user

    def minimum_bid(self):
        return max(self.starting_bid, self.current_winning_bid() + Decimal(0.01))

    def bid_count(self):
        return self.bids.count()

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        form =  kwargs.pop("form", None)
        form = form or self.get_form(request)
        context["form"] = form

        if request.user.is_authenticated and request.user.bids.exists():
            context["user_bid"] = request.user.bids.filter(auction_item=self).order_by("-amount").first()
            
        if self.id:
            context["current_winning_bid"] = self.current_winning_bid()
            context["bid_count"] = self.bid_count()
            context["minimum_bid"] = self.minimum_bid()
            context["auction_closed"] = self.get_parent().specific.is_closed()
            context["auction_open"] = self.get_parent().specific.is_open()
            
        return context

    def winner_notified(self):
        if self.active_bids.exists():
            return self.current_winning_bid_obj.winner_notified
        return False

    def notify_winner(self, request):
        if self.winner_notified():
            return False
        winning_bid = self.current_winning_bid_obj
        if winning_bid:
            send_mail(
                f"PINS Auction: You have won! ({self.title})",
                (
                    "You have won the following PINS auction item:\n"
                    f"{self.title} ({self.get_parent().title})\n"
                    f"{self.get_full_url(request)}\n\n"
                    f"Your total amount due, including shipping is £{self.total_due()}\n\n"
                    "Please make your payment by bank transfer to PINS:\n"
                    "Account name: Podencos in Need - PINS\n"
                    "Account no: 13804187\n"
                    "Sort code: 09-01-29\n\n"
                    "To help us process your item as soon as possible, please include 'Auction' and your name in the "
                    f"reference, and send a screenshot of the transaction to {settings.DEFAULT_ADMIN_EMAIL}\n\n"
                    "Thank you for your support!\n"
                    "The PINS team"
                ),
                [winning_bid.user.email],
                settings.DEFAULT_FROM_EMAIL,
                reply_to=[settings.DEFAULT_ADMIN_EMAIL],
            )
            winning_bid.winner_notified = True
            winning_bid.save()
            winning_bid.write_bid_log(winner_notified=True, changed_by=request.user)
            return True
        return False

    def donor_notified(self):
        if self.active_bids.exists():
            return self.current_winning_bid_obj.donor_notified
        return False

    def notify_donor(self, request):
        if self.donor_notified():
            return False
        winning_bid = self.current_winning_bid_obj
        if winning_bid:
            send_mail(
                f"PINS Auction: Your item has sold! ({self.title})",
                (
                    "Your PINS auction item has been won:\n"
                    f"{self.title} ({self.get_parent().title})\n"
                    f"{self.get_full_url(request)}\n\n"
                    f"Please ship it to:\n\n"
                    f"{winning_bid.format_shipping_details()}\n\n"
                    f"If you requested reimbursement for shipping costs, one of the admin team will be in contact shortly.\n\n"
                    "Thank you for your support!\n"
                    "The PINS team"
                ),
                [self.donor_email],
                settings.DEFAULT_FROM_EMAIL,
                reply_to=[settings.DEFAULT_ADMIN_EMAIL],
            )
            winning_bid.donor_notified = True
            winning_bid.save()
            winning_bid.write_bid_log(donor_notified=True, changed_by=request.user)
            return True
        return False

    def get_logs_url(self):
        return reverse("auction_item_log", args=(self.id,))

    def notify_donor_url(self):
        return reverse("fundraising:notify_auction_item_donor", args=(self.id,))

    def notify_winner_url(self):
        return reverse("fundraising:notify_auction_item_winner", args=(self.id,))
    

class AuctionItemLog(Orderable):
    auction_item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name="logs")
    log = models.TextField()
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-timestamp",)


class Bid(ClusterableModel):
    auction_item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name="bids")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bids")
    amount = models.DecimalField(max_digits=6, decimal_places=2)
    placed_at = models.DateTimeField(default=timezone.now)
    # Whether to notify user by email when they are out-bid
    notify = models.BooleanField(default=True, help_text="Notify me when someone places a higher bid")

    # shipping info
    # This avoids us having to collect address info and hold it on the user model.
    # It also allows for shipping to someone other than the bidder.
    # Make it optional when submitting a bid
    # Have a link to user's bids where they can update it
    name = models.CharField(null=True, blank=True)
    address_line_1 = models.CharField(null=True, blank=True, verbose_name="Street address (1)")
    address_line_2 = models.CharField(null=True, blank=True, verbose_name="Street address (2)")
    address_line_3 = models.CharField(null=True, blank=True, verbose_name="Street address (3)")
    town_city = models.CharField(null=True, blank=True, verbose_name="Town/City")
    county = models.CharField(null=True, blank=True)
    postcode = models.CharField(null=True, blank=True)

    # Admin use only
    # User can delete bid until auction closes. After it closes, an admin can manually withdraw a winning bid
    # if a user doesn't pay or changes their mind. Then the winning bid passes to the next highest.
    withdrawn = models.BooleanField(default=False)
    # This bid was a winning bid, and the user has been emailed notification of their win.
    winner_notified = models.BooleanField(default=False)
    # This bid was a winning bid, and the donor has been emailed shipping details for it.
    donor_notified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} - {self.auction_item} - £{self.amount}"

    def is_winner(self):
        return not self.withdrawn and self.amount == self.auction_item.current_winning_bid()

    def toggle_withdrawn(self, request):
        toggle_to = not self.withdrawn
        action = "withdrawn" if toggle_to is True else "reinstated"
        self.withdrawn = toggle_to
        self.save()

        send_mail(
            "PINS Auction: Your bid has been withdrawn",
            (
                f"An admin has {action} your bid on the following PINS auction item:\n"
                f"{self.auction_item.title} ({self.auction_item.get_parent().title})\n"
                f"{self.auction_item.get_full_url(request)}\n\n"
            ),
            [self.user.email],
            settings.DEFAULT_FROM_EMAIL,
            reply_to=[settings.DEFAULT_ADMIN_EMAIL],
        )
        self.write_bid_log(new_withdrawn_status=toggle_to, changed_by=request.user)
        return toggle_to

    def write_bid_log(
            self, 
            new=False, 
            new_withdrawn_status=None,
            winner_notified=False,
            donor_notified=False,
            changed_by=None,
        ):
        changed_by_str = f" by user {changed_by}" if changed_by else ""
        if winner_notified:
            AuctionItemLog.objects.create(auction_item=self.auction_item, log=f"Winner {self.user} ({self.user.id}) notified{changed_by_str}")
        elif donor_notified:
            AuctionItemLog.objects.create(auction_item=self.auction_item, log=f"Donor {self.auction_item.donor} notified of {self.user}'s win{changed_by_str}") 
        elif new_withdrawn_status is None:
            action = "created" if new else "updated"
            AuctionItemLog.objects.create(auction_item=self.auction_item, log=f"User {self.user} ({self.user.id}) {action} bid: £{self.amount}")
        else:
            match new_withdrawn_status:
                case True:
                    AuctionItemLog.objects.create(auction_item=self.auction_item, log=f"Bid withdrawn for User {self.user} ({self.user.id}){changed_by_str}")
                case False:
                    AuctionItemLog.objects.create(auction_item=self.auction_item, log=f"Bid reinstated for User {self.user} ({self.user.id}){changed_by_str}")
                case _:
                    ...

    def admin_url(self):
        return reverse("auction_item_bid", args=(self.id,))

    def format_shipping_details(self):
        return parse_shipping_address(self, delimiter="\n")

    def save(self):
        if self.id:
            pre_save = Bid.objects.get(id=self.id)
            if pre_save.amount != self.amount:
                self.placed_at = timezone.now()
                self.write_bid_log()
            if pre_save.withdrawn != self.withdrawn:
                self.write_bid_log(new_withdrawn_status=self.withdrawn)
        else:
            self.write_bid_log(new=True)
        
        for field in [self.name, self.address_line_1, self.address_line_2, self.address_line_3, self.town_city, self.county, self.postcode]:
            if field is not None:
                field = field.strip()

        UserShippingAddress.objects.get_or_create(
            user=self.user,
            name=self.name,
            address_line_1=self.address_line_1,
            address_line_2=self.address_line_2,
            address_line_3=self.address_line_3,
            town_city=self.town_city,
            county=self.county,
            postcode=self.postcode,
        )

        super().save()


class UserShippingAddress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    name = models.CharField()
    address_line_1 = models.CharField(verbose_name="Street address (1)")
    address_line_2 = models.CharField(null=True, blank=True, verbose_name="Street address (2)")
    address_line_3 = models.CharField(null=True, blank=True, verbose_name="Street address (3)")
    town_city = models.CharField(verbose_name="Town/City")
    county = models.CharField()
    postcode = models.CharField()

    def parse_address(self):
        return parse_shipping_address(self)


def parse_shipping_address(obj, delimiter=", "):
    return delimiter.join(
            [
                line 
                for line in [obj.name, obj.address_line_1, obj.address_line_2, obj.address_line_3, obj.town_city, obj.county, obj.postcode]
                if line
            ]
        )

class BidForm(forms.ModelForm):

    existing_address = forms.CharField(
        required=False,
        label="Select an existing address",
    )
    class Meta:
        fields = ("amount", "auction_item", "user", "notify", "name", "address_line_1", "address_line_2", "address_line_3", "town_city", "county", "postcode")
        model = Bid
        labels = {
            "address_line_1": "Street address",
            "address_line_2": "Street address (optional)",
            "address_line_3": "Street address (optional)",
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auction_item = self.initial["auction_item"]
        self.helper = FormHelper()
        self.helper.form_show_errors = True
        if self.instance.id:
            id_field = Hidden("id", self.instance.id)
        else:
            id_field = HTML("")
        self.fields["amount"].widget.attrs = {"onWheel": "event.preventDefault();"}
        for field in ["name", "address_line_1", "town_city", "county", "postcode"]:
            self.fields[field].required = True

        user = User.objects.get(id=self.initial["user"]) if self.initial["user"] else None
        user_addresses = user_address_choices(user)
        self.fields["existing_address"].widget = forms.Select(choices=user_addresses)
        if user_addresses:
            for field in ["name", "address_line_1", "town_city", "county", "postcode"]:
                self.fields[field].required = False

        self.helper.layout = Layout(
            Hidden("user", self.initial["user"]),
            Hidden("auction_item", self.auction_item),
            id_field,
            PrependedText("amount", "£"),
            "notify",
            Fieldset(
                "Shipping information",
                HTML("<small>This information is required for shipping the item if you win the auction.</small>"),
                "existing_address",
                Submit('submit', f'Submit', css_class="btn btn-success"),
                HTML("<p>OR enter a new address:</p>"),
                "name", 
                "address_line_1", 
                "address_line_2", 
                "address_line_3", 
                "town_city", 
                "county", 
                "postcode"
            ),
            Submit('submit', f'Submit', css_class="btn btn-success"),
        )

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        auction_item = AuctionItem.objects.get(id=self.auction_item)
        if self.instance.id and value < self.instance.amount:
            if value < auction_item.minimum_bid():
                raise ValidationError(f"Please enter an amount of at least £{auction_item.minimum_bid():.2f}")
        return value

    def clean(self):
        if self.cleaned_data.get("existing_address"):
            address = UserShippingAddress.objects.get(id=self.cleaned_data['existing_address'])
            for field in [
                "name", 
                "address_line_1", 
                "address_line_2", 
                "address_line_3", 
                "town_city", 
                "county", 
                "postcode"
            ]:
                self.cleaned_data[field] = getattr(address, field)
        else:
            for field in ["name", "address_line_1", "town_city", "county", "postcode"]:
                field_data = self.cleaned_data.get(field)
                if not field_data:
                    self.add_error(field, "This field is required.")