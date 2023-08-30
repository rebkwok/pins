from django.conf import settings
from django.db import models
from django.template.response import TemplateResponse

from modelcluster.fields import ParentalKey

from wagtail.admin.panels import (
    FieldPanel,
    FieldRowPanel,
    InlinePanel,
    HelpPanel,
    MultiFieldPanel,
    PublishingPanel,
)
from wagtail.contrib.forms.models import AbstractEmailForm, AbstractFormField
from wagtail.fields import RichTextField
from wagtail.models import (
    DraftStateMixin,
    Orderable,
    Page,
    PreviewableMixin,
    RevisionMixin,
    TranslatableMixin,
)


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
                        FieldPanel("featured_section"),
                        FieldPanel("featured_section_show_more_text")
                    ]
                ),
                MultiFieldPanel(
                    [
                        FieldPanel("page_link_1_title"),
                        FieldPanel("page_link_1"),
                        FieldPanel("page_link_1_btn_text"),
                    ]
                ),
                MultiFieldPanel(
                    [
                        FieldPanel("page_link_2_title"),
                        FieldPanel("page_link_2"),
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

    def save(self, *args, **kwargs):
        self.from_address = settings.DEFAULT_FROM_EMAIL
        super().save(*args, **kwargs)


class OrderFormField(AbstractFormField):
    """
    for contact form and adoption application form:
    https://docs.wagtail.org/en/stable/reference/contrib/forms/index.html
    """
    page = ParentalKey("OrderFormPage", related_name="order_form_fields", on_delete=models.CASCADE)


class ProductVariant(Orderable):
    page = ParentalKey("OrderFormPage", related_name="product_variants", on_delete=models.CASCADE)
    description = models.CharField(blank=True, max_length=250)
    cost = models.DecimalField(max_digits=10, decimal_places=2)

class OrderFormPage(AbstractEmailForm):

    body = RichTextField(blank=True)
    image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.SET_NULL, related_name='+', blank=True, null=True
    )

    product_name = models.CharField(blank=True, max_length=250)
    product_description = models.CharField(blank=True, max_length=250)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2)

    thank_you_text = RichTextField(blank=True)

    # Note how we include the FormField object via an InlinePanel using the
    # related_name value
    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("body"),
        MultiFieldPanel(
            [
                FieldPanel("image"),
                FieldPanel("product_name"),
                FieldPanel("product_description"),
                FieldPanel("shipping_cost"),
                InlinePanel(
                    "product_variants", label="Product Variants",
                ),
            ],
            "Product details"
        ),
        HelpPanel(
            content="""
            Add fields for name, address etc., plus quantity fields.

            Add a dropdown field labelled quantity_n for each product variant in order (starting at 1).

            NOTE: Do NOT change the quantity label after creation. Delete and recreate if necessary.
            """),
        InlinePanel("order_form_fields", heading="Form fields", label="Field"),
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

    def default_total(self):
        return self.product_variants.first().cost + self.shipping_cost

    def get_form_fields(self):
        return self.order_form_fields.all()
    
    def get_variant_quantities_and_total(self, data):
        def get_item(v):
            if isinstance(v, list):
                return int(v[0])
            return int(v)        
        quantities = {
            k: get_item(v) for k, v in data.items() if k.startswith("quantity_")
        }
        total = 0
        variant_quantities = {}
        for key, quantity in quantities.items():
            variant_id = key.strip("quantity_")
            variant = self.product_variants.get(id=variant_id)
            variant_quantities[key] = (variant, quantity)
            total += (variant.cost * quantity)
        total += self.shipping_cost

        return variant_quantities, total

    def render_email(self, form):
        content = super().render_email(form)
        variant_quantities, total = self.get_variant_quantities_and_total(form.cleaned_data)
        
        for key, (variant, _) in variant_quantities.items():
            content = content.replace(key, f"{variant.description} ({key})")
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
        help_text="Landscape mode only; horizontal width between 1000px and 3000px.",
    )
    body = RichTextField(verbose_name="Page body", blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("introduction"),
        FieldPanel("body"),
        FieldPanel("image"),
    ]

    parent_page_types = ["HomePage"]
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

