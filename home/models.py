import datetime

from django.conf import settings
from django.db import models
from django.template.response import TemplateResponse
from django.utils.formats import date_format

from modelcluster.fields import ParentalKey

from wagtail.admin.mail import send_mail
from wagtail.admin.panels import (
    FieldPanel,
    FieldRowPanel,
    InlinePanel,
    HelpPanel,
    MultiFieldPanel,
    PublishingPanel,
)
from wagtail.contrib.forms.models import AbstractEmailForm, AbstractFormField
from wagtail.contrib.forms.views import SubmissionsListView
from wagtail.fields import RichTextField
from wagtail.models import (
    DraftStateMixin,
    Orderable,
    Page,
    PreviewableMixin,
    RevisionMixin,
    TranslatableMixin,
)
from wagtail.contrib.forms.utils import get_field_clean_name


class HomePage(Page):
    """
    The Home Page. This looks slightly more complicated than it is. You can
    see if you visit your site and edit the homepage that it is split between
    a:
    - Hero area
    - Body area
    - A promotional area
    - A featured site section
    - Links to other pages
    """

    # Hero section of HomePage
    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Homepage image",
    )
    hero_text = models.CharField(
        max_length=255, help_text="Write a  short introduction for the home page"
    )
    hero_cta = models.CharField(
        verbose_name="Hero CTA",
        max_length=255,
        help_text="Text to display on Call to Action",
    )
    hero_cta_link = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Hero CTA link",
        help_text="Choose a page to link to for the Call to Action",
    )

    # Body section of the HomePage
    body = RichTextField(help_text="Main body text for the home page")

    # Promo section of the HomePage
    promo_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Promo image",
    )
    promo_title = models.CharField(
        blank=True, max_length=255, help_text="Title to display above the promo copy"
    )
    promo_text = RichTextField(
        null=True, blank=True, max_length=1000, help_text="Write some promotional copy"
    )

    # Featured sections on the HomePage
    # You will see on templates/base/home_page.html that these are treated
    # in different ways, and displayed in different areas of the page.
    # Each list their children items that we access via the children function
    # that we define on the individual Page models e.g. BlogIndexPage
    featured_section_title = models.CharField(
        blank=True, max_length=255, help_text="Title to display above the promo copy"
    )
    featured_section_body = RichTextField(
        null=True, blank=True, max_length=1000, help_text="Optional description for the featured section"
    )
    featured_section = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="First featured section for the homepage. Will display up to "
        "three child items.",
        verbose_name="Featured section 1",
    )
    featured_section_show_more_text = models.CharField(
        blank=True, max_length=255, help_text="Text to display for link to featured section"
    )

    page_link_1_title = models.CharField(
        blank=True, max_length=255, help_text="Title to display for first page link"
    )
    page_link_1 = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="First page link for the homepage.",
        verbose_name="Page link 1",
    )
    page_link_1_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Background image",
    )
    page_link_1_btn_text = models.CharField(
        blank=True, max_length=255, help_text="Text to display on first page link button"
    )

    page_link_2_title = models.CharField(
        blank=True, max_length=255, help_text="Title to display for second page link"
    )
    page_link_2 = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Second page link for the homepage.",
        verbose_name="Page link 2",
    )
    page_link_2_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Background image",
    )
    page_link_2_btn_text = models.CharField(
        blank=True, max_length=255, help_text="Text to display on second page link button"
    )

    hero_footer_text = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Text to display on the home page footer image"
    )
    hero_footer = models.CharField(
        verbose_name="Hero Footer",
        max_length=255,
        null=True,
        blank=True,
        help_text="Text to display on the Footer link button",
    )
    hero_footer_link = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Hero CTA link",
        help_text="Choose a page to link to for the Footer",
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel("image"),
                FieldPanel("hero_text"),
                MultiFieldPanel(
                    [
                        FieldPanel("hero_cta"),
                        FieldPanel("hero_cta_link"),
                    ]
                ),
            ],
            heading="Hero section",
        ),
        MultiFieldPanel(
            [
                FieldPanel("promo_image"),
                FieldPanel("promo_title"),
                FieldPanel("promo_text"),
            ],
            heading="Promo section",
        ),
        FieldPanel("body"),
        MultiFieldPanel(
            [
                MultiFieldPanel(
                    [
                        FieldPanel("featured_section_title"),
                        FieldPanel("featured_section_body"),
                        FieldPanel("featured_section"),
                        FieldPanel("featured_section_show_more_text")
                    ]
                ),
                MultiFieldPanel(
                    [
                        FieldPanel("page_link_1_title"),
                        FieldPanel("page_link_1"),
                        FieldPanel("page_link_1_image"),
                        FieldPanel("page_link_1_btn_text"),
                    ]
                ),
                MultiFieldPanel(
                    [
                        FieldPanel("page_link_2_title"),
                        FieldPanel("page_link_2"),
                        FieldPanel("page_link_2_image"),
                        FieldPanel("page_link_2_btn_text"),
                    ]
                ),
            ],
            heading="Featured homepage sections",
        ),
        MultiFieldPanel(
            [
                FieldPanel("hero_footer_text"),
                MultiFieldPanel(
                    [
                        FieldPanel("hero_footer"),
                        FieldPanel("hero_footer_link"),
                    ]
                ),
            ],
            heading="Hero footer section",
        ),
    ]

    def __str__(self):
        return self.title


class FormField(AbstractFormField):
    """
    for contact form and adoption application form:
    https://docs.wagtail.org/en/stable/reference/contrib/forms/index.html
    """

    page = ParentalKey("FormPage", related_name="form_fields", on_delete=models.CASCADE)


class FormPage(AbstractEmailForm):

    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    body = RichTextField(blank=True)
    thank_you_text = RichTextField(blank=True)

    # Note how we include the FormField object via an InlinePanel using the
    # related_name value
    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("image"),
        FieldPanel("body"),
        InlinePanel("form_fields", heading="Form fields", label="Field"),
        FieldPanel("thank_you_text"),
        MultiFieldPanel(
            [
                FieldRowPanel(
                    [
                        FieldPanel("to_address"),
                    ]
                ),
                FieldPanel("subject"),
            ],
            "Email",
        ),
    ]

    subpage_types = []

    def serve(self, request, *args, **kwargs):
        self.ref = request.GET.get("ref")
        return super().serve(request, *args, **kwargs)

    def get_form(self, *args, **kwargs):
        form = super().get_form(*args, **kwargs)
        if self.ref and "subject" in form.fields:
            form.fields["subject"].initial = f"Enquiry about {self.ref}"
        return form

    def save(self, *args, **kwargs):
        self.from_address = settings.DEFAULT_FROM_EMAIL
        super().save(*args, **kwargs)

    def send_mail(self, form):
        addresses = [x.strip() for x in self.to_address.split(",")]
        reply_to = form.data.get("email_address")
        subject = form.data.get("subject", self.subject)
        send_mail(
            subject,
            self.render_email(form),
            addresses,
            self.from_address,
            reply_to=[reply_to]
        )

    def render_email(self, form):
        skip_fields = ["subject"]
        content = []

        cleaned_data = form.cleaned_data
        for field in form:
            if field.name not in cleaned_data or field.name in skip_fields:
                continue

            value = cleaned_data.get(field.name)

            if isinstance(value, list):
                value = ", ".join(value)

            # Format dates and datetime(s) with SHORT_DATE(TIME)_FORMAT
            if isinstance(value, datetime.datetime):
                value = date_format(value, settings.SHORT_DATETIME_FORMAT)
            elif isinstance(value, datetime.date):
                value = date_format(value, settings.SHORT_DATE_FORMAT)

            if field.name == "message":
                content.append(f"{field.label}:\n{value}")
            elif field.name == "email_address":
                content.append(f"From: {value}")
            else:
                content.append(f"{field.label}: {value}")

        return "\n\n".join(content)


class OrderFormField(AbstractFormField):
    """
    for contact form and adoption application form:
    https://docs.wagtail.org/en/stable/reference/contrib/forms/index.html
    """
    page = ParentalKey("OrderFormPage", related_name="order_form_fields", on_delete=models.CASCADE)

    def get_field_clean_name(self):
        # if clean name is already set, just return it
        if self.clean_name:
            return self.clean_name
        return get_field_clean_name(self.label)


class ProductVariant(Orderable):
    page = ParentalKey("OrderFormPage", related_name="product_variants", on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    description = models.CharField(blank=True, max_length=250)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    item_count = models.PositiveIntegerField(
        default=1, 
        help_text="The number of individual items represented by this variant, used for "
                   "stock checking. i.e. A pack of 5 = 5 items"
    )
    quantity_choices = models.CharField(
        max_length=255, 
        default="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20",
        help_text="Comma separated list of quantity choices for the drop down menu"
    )
    slug = models.CharField(max_length=60, blank=True, default="", help_text="This field will be autopoulated")
    
    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = f"pv__{get_field_clean_name(self.name)}"
            slug = base_slug
            counter = 0
            while ProductVariant.objects.filter(page=self.page, slug=slug).exclude(id=self.id).exists():
                counter += 1
                slug = f"{base_slug}_{counter}"
            self.slug = slug
        super().save(*args, **kwargs)


class OrderFormSubmissionsListView(SubmissionsListView):

    def stream_csv(self, queryset):
        self.list_export += ["total"]
        self.export_headings.update({"total": "Total (£)"})
        return super().stream_csv(queryset)

    def write_xlsx(self, queryset, output):
        self.list_export += ["total"]
        self.export_headings.update({"total": "Total (£)"})
        return super().write_xlsx(queryset, output)

    def to_row_dict(self, item):
        """Orders the submission dictionary for spreadsheet writing"""
        row_dict = super().to_row_dict(item)
        _, total = self.form_page.get_variant_quantities_and_total(row_dict)
        row_dict["total"] = total
        return row_dict

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        if not self.is_export:
            context_data["data_headings"].append({'name': 'total', 'label': 'Total (£)', 'order': None})
            fields = self.form_page.get_data_fields()
            for row in context_data["data_rows"]:
                form_data = row["fields"]
                form_data_dict = {field[0]: form_data[i] for i, field in enumerate(fields)}
                _, total = self.form_page.get_variant_quantities_and_total(form_data_dict)
                form_data.append(total)
        return context_data


class OrderFormPage(AbstractEmailForm):

    submissions_list_view_class = OrderFormSubmissionsListView

    body = RichTextField(blank=True)
    image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.SET_NULL, related_name='+', blank=True, null=True,
        help_text="Used for the hero image",
    )
    inline_image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.SET_NULL, related_name='+', blank=True, null=True,
        help_text="Displayed before the body"
    )
    product_name = models.CharField(blank=True, max_length=250)
    product_description = models.CharField(blank=True, max_length=250)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2)
    total_available = models.PositiveIntegerField(
        null=True, blank=True, help_text="Max total number available (optional)"
    )
    form_footer_text = RichTextField(blank=True)
    thank_you_text = RichTextField(blank=True)
    

    # Note how we include the FormField object via an InlinePanel using the
    # related_name value
    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("image"),
        FieldPanel("inline_image"),
        FieldPanel("body"),
        MultiFieldPanel(
            [
                FieldPanel("product_name"),
                FieldPanel("product_description"),
                FieldPanel("shipping_cost"),
                FieldPanel("total_available"),
                InlinePanel(
                    "product_variants", label="Product Variants", 
                    panels=[
                        FieldPanel("name"),
                        FieldPanel("description"),
                        FieldPanel("cost"),
                        FieldPanel("item_count"),
                        FieldPanel("quantity_choices"),
                    ]
                ),
            ],
            "Product details"
        ),
        HelpPanel(
            content="""
            Add fields for name, address etc.
            Quantity fields will be added when the page is published 
            and updated automatically based on product variants.  
            Note they will not show in the preview until published.
            Changes to the label or choices in these fields will have no effect - change
            the product variant name/choices instead.
            """),
        InlinePanel("order_form_fields", heading="Form fields", label="Field"),
        FieldPanel("form_footer_text"),
        FieldPanel("thank_you_text"),
        MultiFieldPanel(
            [
                FieldRowPanel(
                    [
                        FieldPanel("to_address"),
                    ]
                ),
                FieldPanel("subject"),
            ],
            "Email",
        ),
    ]

    subpage_types = []

    def save(self, *args, **kwargs):
        self.from_address = settings.DEFAULT_FROM_EMAIL
        super().save(*args, **kwargs)
        # Save the product variants to ensure slugs have been generated
        for pr in self.product_variants.all():
            pr.save()
        # generate/update quantity fields
        for slug in self.product_variant_slugs:
            self.create_or_update_order_form_field(slug)
        fields_to_remove = self.product_quantity_field_names - self.product_variant_slugs
        for field_name in fields_to_remove:
            self.order_form_fields.get(clean_name=field_name).delete()        

    def create_or_update_order_form_field(self, product_variant_slug):
        variant = self.product_variants.get(slug=product_variant_slug)
        try:
            field = self.order_form_fields.get(clean_name=product_variant_slug)
        except OrderFormField.DoesNotExist:
            field = self.order_form_fields.create(
                page_id=self.pk, 
                clean_name=product_variant_slug, 
                label=variant.name,
                field_type="dropdown", 
                default_value = 0
            )
        if (field.choices != variant.quantity_choices) or (field.label != variant.name): 
            field.choices = variant.quantity_choices
            field.label = variant.name
            field.save()

    @property
    def product_quantity_field_names(self):
        return set(self.order_form_fields.filter(clean_name__startswith="pv__").values_list("clean_name", flat=True))

    @property
    def product_variant_slugs(self):
        return set(self.product_variants.values_list("slug", flat=True))

    def get_form_fields(self):
        return self.order_form_fields.all()
    
    def _get_quantities(self, data):
        def get_item(v):
            if isinstance(v, list):
                return int(v[0])
            return int(v)     
        return {
            k: get_item(v) for k, v in data.items() if k in self.product_variant_slugs
        }

    def get_variant_quantities_and_total(self, data):
        quantities = self._get_quantities(data)
        total = 0
        variant_quantities = {}
        for key, quantity in quantities.items():
            variant = self.product_variants.get(slug=key)
            variant_quantities[key] = (variant, quantity)
            total += (variant.cost * quantity)
        if total > 0:
            total += self.shipping_cost

        return variant_quantities, total

    def _item_counts_per_variant(self):
        return dict(self.product_variants.values_list("slug", "item_count"))

    def sold_out(self):
        if self.total_available is None:
            return False
        return self.get_total_quantity_ordered() >= self.total_available

    def disallowed_variants(self):
        if self.total_available is None:
            return []
        quantity_ordered_so_far = self.get_total_quantity_ordered()
        remaining_stock = self.total_available - quantity_ordered_so_far 
        item_counts_per_variant = self._item_counts_per_variant()
        return [
            variant for variant in self.product_variants.all()
            if item_counts_per_variant[variant.slug] > remaining_stock
        ]

    def get_total_quantity_ordered(self):
        submissions = self.formsubmission_set.all()
        item_counts_per_variant = self._item_counts_per_variant()
        total = 0
        for submission in submissions:
            total += self.quantity_ordered_by_submission(submission.form_data, item_counts_per_variant)
        return total

    def quantity_ordered_by_submission(self, form_data, item_counts_per_variant=None):
        if item_counts_per_variant is None:
            item_counts_per_variant = self._item_counts_per_variant()
        quantities = self._get_quantities(form_data)
        number_of_items = 0
        for key, quantity in quantities.items():
            number_of_items += item_counts_per_variant[key] * quantity
        return number_of_items

    def render_email(self, form):
        content = super().render_email(form)
        _, total = self.get_variant_quantities_and_total(form.cleaned_data)
        content += f"\nTotal amount due: £{total}"
        return content
    
    def render_landing_page(self, request, form_submission=None, *args, **kwargs):
        context = self.get_context(request)
        context["form_submission"] = form_submission
        _, total = self.get_variant_quantities_and_total(form_submission.get_data())
        context["total"] = total
        return TemplateResponse(
            request, self.get_landing_page_template(request), context
        )


class StandardPage(Page):
    """
    A generic content page.
    """
    introduction = models.TextField(help_text="Text to describe the page", blank=True)
    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Displayed as the hero image. Landscape mode only; horizontal width between 1000px and 3000px.",
    )
    inline_image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.SET_NULL, related_name='+', blank=True, null=True,
        help_text="Displayed afer the introduction"
    )
    body = RichTextField(verbose_name="Page body", blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("introduction"),
        FieldPanel("body"),
        FieldPanel("image"),
    ]

    parent_page_types = ["HomePage", "OrderFormPage"]
    subpage_types = []


class FAQPage(Page):
    
    introduction = RichTextField(null=True, blank=True, help_text="Optional introduction text")

    content_panels = Page.content_panels + [
        FieldPanel('introduction',),
        InlinePanel('faqs', label="FAQs")
    ]

    parent_page_types = ["HomePage"]
    subpage_types = []

    class Meta:
        verbose_name = "FAQ Page"


class FAQ(Orderable):
    page = ParentalKey(FAQPage, on_delete=models.CASCADE, related_name='faqs')
    question = models.CharField(max_length=255)
    answer = RichTextField()

    panels = [
        FieldPanel('question'),
        FieldPanel('answer'),
    ]


class FooterText(
    DraftStateMixin,
    RevisionMixin,
    PreviewableMixin,
    TranslatableMixin,
    models.Model,
):
    """
    This provides editable text for the site footer. It is registered
    using `register_snippet` as a function in wagtail_hooks.py to be grouped
    together with the Person model inside the same main menu item. It is made
    accessible on the template via a template tag defined in base/templatetags/
    navigation_tags.py
    """

    body = RichTextField()

    panels = [
        HelpPanel(
            """Footer added to every page. Note that if more than one footer text is
              defined, the most recently created published version will be used."""),
        FieldPanel("body"),
        PublishingPanel(),
    ]

    def __str__(self):
        return "Footer text"

    def get_preview_template(self, request, mode_name):
        return "base.html"

    def get_preview_context(self, request, mode_name):
        return {"footer_text": self.body}

    class Meta(TranslatableMixin.Meta):
        verbose_name_plural = "Footer Text"

