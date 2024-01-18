import uuid
from django.db import models
from django.urls import reverse
from django.utils import timezone


PAGE_TYPE_COSTS = {
    "single": 5,
    "double": 10,
    "single_with_facing": 10,
    "photo": 5,
}


def image_upload_path(instance, filename):
        # file will be uploaded to MEDIA_ROOT/recipes/<reference>/<filename>
        return f"recipes/{instance.reference}/{filename}"



class RecipeBookSubmission(models.Model):

    page_types = (
        ("single", "Single recipe page"),
        ("double", "Double recipe page"),
        ("single_with_facing", "Single page recipe with full page facing photo"),
        ("photo", "Photo page only")
    )
    # fields that apply to all page types
    reference = models.UUIDField(
        primary_key=True,
        default = uuid.uuid4, 
        editable = False
    )

    name = models.CharField(help_text="Your name")
    email = models.EmailField(help_text="Your email; we will send a copy of your submission to this address")

    page_type = models.CharField(choices=page_types)

    # recipe fields, applies to all except photo page types
    title = models.CharField(help_text="Title of recipe", blank=True)
    preparation_time = models.CharField(help_text="Preparation time (please include units)", blank=True)
    cook_time = models.CharField(help_text="Cook time (please include units)", blank=True)

    servings = models.CharField(help_text="How many servings does the recipe make? e.g. serves 4, makes 16", blank=True)
    ingredients = models.TextField(help_text="List ingredients as they should appear in the recipe (include subheadings if you want)", blank=True)
    method = models.TextField(help_text="Method; please separate paragraphs with a blank line", blank=True)

    submitted_by = models.CharField(
        help_text=(
            "Name(s) for the 'Submitted by' section in the recipe. This can be your full name, your first "
            "name, your dog's name - however you want it to appear e.g. 'Becky & Nala'. This will appear "
            "next to your profile image."
        ), 
        blank=True
    )
    profile_image = models.ImageField(
        null=True,
        blank=True,
        upload_to=image_upload_path
    )
    profile_caption = models.TextField(
        help_text=(
            "Optional caption to go with your profile image. E.g. Say something about the recipe, about why you "
            "chose it, or about your dog(s), when they were adopted etc."
        ), 
        blank=True
    )

    # Applies to double, single_with_facing and photo pages only
    photo = models.ImageField(
        null=True,
        blank=True,
        upload_to=image_upload_path
    )
    # Applies to double and photo pages only
    photo_caption = models.CharField(null=True, blank=True)

    # Admin and payments, applies to all
    date_submitted = models.DateTimeField(default=timezone.now)
    paid = models.BooleanField(default=False)
    date_paid = models.DateTimeField(null=True, blank=True)
    processing = models.BooleanField(default=False)
    complete = models.BooleanField(default=False)

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

    def page_type_verbose(self):
         return dict(self.page_types)[self.page_type]
    page_type_verbose.short_description = "Page type"

    def formatted_cost(self):
         return f"£{self.cost:.2f}"
    formatted_cost.short_description = "Cost"

    def get_absolute_url(self):
        return reverse("fundraising:recipe_book_contribution_detail", kwargs={"pk": self.reference})
    