import datetime
import re

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug
from django.db import models
from django.template.response import TemplateResponse
from django.utils.formats import date_format
from django.urls import reverse

from shortuuid.django_fields import ShortUUIDField

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
from wagtail.contrib.forms.forms import FormBuilder, BaseForm
from wagtail.contrib.forms.models import AbstractEmailForm, AbstractFormField, AbstractFormSubmission
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

from wagtailcaptcha.models import WagtailCaptchaEmailForm, WagtailCaptchaForm, WagtailCaptchaFormBuilder

from payments.utils import get_paypal_form


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


class FormPage(WagtailCaptchaEmailForm):

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

    template_name = "home/order_list_submissions_index.html"

    def stream_csv(self, queryset):
        self.list_export += ["total", "total_items", "paid", "shipped"]
        self.export_headings.update(
            {"total": "Total (£)", "total_items": "Total items", "paid": "Paid", "shipped": "Shipped"}
        )
        return super().stream_csv(queryset)

    def write_xlsx(self, queryset, output):
        self.list_export += ["reference", "total", "total_items", "paid", "shipped"]
        self.export_headings.update(
            {
                "reference": "Reference",
                "total": "Total (£)", 
                "total_items": "Total items", 
                "paid": "Paid", 
                "shipped": "Shipped"
            }
        )
        return super().write_xlsx(queryset, output)

    def to_row_dict(self, item):
        """Orders the submission dictionary for spreadsheet writing"""
        row_dict = super().to_row_dict(item)
        row_dict["reference"] = item.reference
        row_dict["total"] = item.cost
        row_dict["total_items"] = self.form_page.quantity_ordered_by_submission(row_dict)
        row_dict["paid"] = "Y" if item.paid else "-"
        row_dict["shipped"] = "Y" if item.shipped else "-"
        return row_dict

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        if not self.is_export:
            total_ordered_so_far = self.form_page.get_total_quantity_ordered()
            if self.form_page.total_available:
                remaining_stock = self.form_page.total_available - total_ordered_so_far
            else:
                remaining_stock = "N/A"
            context_data["description"] = f"Total sold: {total_ordered_so_far} | Remaining stock: {remaining_stock}"
            extra_cols = [
                {"name": "reference", "label": "Reference", "order": 0},
                {'name': 'total', 'label': 'Total (£)', 'order': None},
                {'name': 'total_items', 'label': 'Total items', 'order': None},
                {'name': 'paid', 'label': 'Paid', 'order': None},
                {'name': 'shipped', 'label': 'Shipped', 'order': None},
            ]
            context_data["data_headings"].extend(extra_cols)
            fields = self.form_page.get_data_fields()

            submissions = OrderFormSubmission.objects.filter(
                id__in=[row["model_id"] for row in context_data["data_rows"]]
            )
            submission_reference = {sub.id: sub.reference for sub in submissions}
            submission_cost = {sub.id: sub.cost for sub in submissions}
            submission_paid_shipped = {
                sub.id: ("Y" if sub.paid else "-", "Y" if sub.shipped else "-") 
                for sub in submissions
            }

            for row in context_data["data_rows"]:
                form_data = row["fields"]
                form_data_dict = {field[0]: form_data[i] for i, field in enumerate(fields)}
                total_items = self.form_page.quantity_ordered_by_submission(form_data_dict)
                extra_form_data = [
                    submission_reference[row["model_id"]], submission_cost[row["model_id"]], total_items, *submission_paid_shipped[row["model_id"]]
                ]
                form_data.extend(extra_form_data)

        return context_data


class OrderVoucher(Orderable):
    """
    Simple code that gives a discount on an order (e.g. if collecting, can remove shipping cost)
    """
    order_form_page = ParentalKey("OrderFormPage", related_name="voucher_codes", on_delete=models.CASCADE)
    code = models.CharField(max_length=20, validators=[validate_slug])
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # so we can deactivate vouchers
    active = models.BooleanField(default=True)


class OrderBaseForm(BaseForm):

    def clean(self):
        super().clean()

        voucher_code = self.cleaned_data.get("voucher_code", "").strip()
        if voucher_code and voucher_code not in self.page.voucher_codes.filter(code=voucher_code, active=True):
            del self.cleaned_data["voucher_code"]
        allowed, validation_error_msg = self.page.quantity_submitted_is_valid(self.cleaned_data)
        if not allowed:
            self.add_error("__all__", validation_error_msg)


class OrderFormBuilder(WagtailCaptchaFormBuilder):

    def __init__(self, fields, **kwargs):
        self.page = kwargs.pop("page")
        super().__init__(fields)

    @property
    def formfields(self):
        original_fields = super().formfields        
        if self.page.voucher_codes.filter(active=True).exists():
            formfields = {
                k: v for k, v in original_fields.items() if k != "wagtailcaptcha"
            }
            voucher_code_field = forms.CharField(
                required=False,
                help_text="If you have a voucher code, enter it here."
            )
            voucher_code_field.widget.attrs.update(
                {
                    "hx-post": f"{reverse('orders:calculate_order_total', args=(self.page.id,))}",
                    "hx-trigger": "keyup changed delay:0.3s",
                    "hx-target": "#order-total"
                }
            )
            formfields.update(
                {
                    "voucher_code": voucher_code_field, 
                    "wagtailcaptcha": original_fields["wagtailcaptcha"]
                }
            )
            return formfields
        return original_fields

    def get_form_class(self):
        return type("WagtailForm", (OrderBaseForm,), self.formfields)


class OrderFormPage(WagtailCaptchaEmailForm):
    form_builder = OrderFormBuilder
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
        MultiFieldPanel(
            [
                HelpPanel(
                    content="""
                    Voucher codes that can be used to apply a discount amount to
                    orders placed using this form. E.g. a discount equivalent to 
                    the shipping cost that can be given out to people who will
                    collect and don't require shipping.
                    """
                ),
                InlinePanel(
                    "voucher_codes", label="Voucher codes", 
                    panels=[
                        FieldPanel("code"),
                        FieldPanel("amount"),
                        FieldPanel("active"),
                    ]
                ),
            ],
            "Voucher codes",
        )
    ]

    end_of_form_field_names = ["wagtailcaptcha", "voucher_code"]
    subpage_types = []

    def clean(self, *args, **kwargs):
        super().clean(*args, **kwargs)
        if not set(self.order_form_fields.values_list("clean_name", flat=True)) & {"email", "email_address"}:
            raise ValidationError(
                {"__all__": ["'Email' or 'Email address' field is required."]}
            )
    
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
    
    def get_form_class(self):
        fb = self.form_builder(self.get_form_fields(), page=self)
        return fb.get_form_class()

    def _get_quantities(self, data):
        def get_item(v):
            if isinstance(v, list):
                return int(v[0])
            return int(v)     
        return {
            k: get_item(v) for k, v in data.items() if k in self.product_variant_slugs
        }

    def default_total(self):
        data = {
            field.clean_name: field.default_value for field in self.get_form_fields() 
            if field.clean_name in self.product_quantity_field_names
        }
        _, total, _ = self.get_variant_quantities_and_total(data)
        return total

    def get_variant_quantities_and_total(self, data):
        code = data.get("voucher_code", "")
        if isinstance(code, list):
            code = code[0]
        code = code.strip()
        voucher_amount = 0
        if code and self.voucher_codes.filter(code=code, active=True).exists():
            voucher_amount = OrderVoucher.objects.get(code=code, active=True).amount
        quantities = self._get_quantities(data)
        total = 0
        variant_quantities = {}
        for key, quantity in quantities.items():
            variant = self.product_variants.get(slug=key)
            variant_quantities[key] = (variant, quantity)
            total += (variant.cost * quantity)
        if total > 0:
            total += self.shipping_cost
            total -= voucher_amount

        return variant_quantities, total, voucher_amount

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

    def quantity_submitted_is_valid(self, form_data):
        validation_error_msg = ""
        if self.total_available is None:
            return True, validation_error_msg
        total_ordered_so_far = self.get_total_quantity_ordered()
        total_for_this_order = self.quantity_ordered_by_submission(form_data)
        remaining_stock = self.total_available - total_ordered_so_far
        valid = total_for_this_order <= remaining_stock
        if not valid:
            validation_error_msg  = f"Quantity selected is unavailable; select a maximum of {remaining_stock} total items."
        return valid, validation_error_msg

    def render_email(self, form):
        content = super().render_email(form)
        _, total, discount = self.get_variant_quantities_and_total(form.cleaned_data)
        content += f"\nTotal items ordered: {self.quantity_ordered_by_submission(form.cleaned_data)}"
        if discount:
            content += f"\nDiscount: {discount}"
        content += f"\nTotal amount due: £{total}"
        return content

    def render_email_for_purchaser(self, form, submission):
        content = self.render_email(form)
        content += f"\n\nView your submission at https://{settings.DOMAIN}{submission.get_absolute_url()}"
        content += f"\nIf you haven't made your payment yet, you'll also find a link there."
        return content
    
    def render_landing_page(self, request, form_submission=None, *args, **kwargs):
        context = self.get_context(request)
        context["form_submission"] = form_submission
        _, total, _ = self.get_variant_quantities_and_total(form_submission.get_data())
        
        context["total"] = total
        context["paypal_form"] = get_paypal_form(
            request=request,
            amount=total, 
            item_name=f"Order form submission: {self.title}",
            reference=form_submission.reference
        )
        return TemplateResponse(
            request, self.get_landing_page_template(request), context
        )

    def get_submission_class(self):
        return OrderFormSubmission
        
    def process_form_submission(self, form):
        """
        Accepts form instance with submitted data, user and page.
        Creates submission instance.

        Set cost here to set the cost at the time of submission (in case prices)
        changed or voucher codes were deactivated
        """
        # Super() sends the email to the to_address
        submission = super().process_form_submission(form)
        _, total, _ = self.get_variant_quantities_and_total(form.cleaned_data)
        submission.cost = total
        submission.save()

        # Send email to purchaser
        send_mail(
            self.subject,
            self.render_email_for_purchaser(form, submission),
            [submission.email],
            settings.DEFAULT_FROM_EMAIL,
            reply_to=[settings.CC_EMAIL],
        )

        return submission
    

class OrderFormSubmission(AbstractFormSubmission):
    reference = ShortUUIDField(
        editable = False
    )
    paid = models.BooleanField(default=False)
    shipped = models.BooleanField(default=False)
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True)

    @property
    def email(self):
        email_field = next((k for k in self.form_data if k in ["email", "email_address"]))
        return self.form_data[email_field]

    def mark_paid(self):
        self.paid = True
        self.save()
    
    def mark_shipped(self):
        self.shipped = True
        self.save()

    def reset(self):
        self.paid = False
        self.shipped = False
        self.save()

    def items_ordered(self):
        variant_quantities, _, _ = self.page.orderformpage.get_variant_quantities_and_total(self.form_data)
        return [variant for variant in variant_quantities.values() if variant[1] > 0]

    def status(self):
        if self.paid:
            if self.shipped:
                return "Paid and shipped"
            else:
                return "Paid"
        else:
            return "Payment pending"

    def status_colour(self):
        colours = {
            "Paid and shipped": "success",
            "Paid": "primary"
        }
        return colours.get(self.status(), "danger")

    def get_absolute_url(self):
        return reverse("orders:order_detail", kwargs={"reference": self.reference})
    

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

    button_text = models.CharField(blank=True)
    button_url = models.URLField(blank=True)
    button_display = models.CharField(
        choices=[("top", "Top of page"), ("bottom", "Bottom of page"), ("both", "Top and bottom of page")],
        default="top"
        )
    button_styling = models.CharField(blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("introduction"),
        FieldPanel("body"),
        FieldPanel("image"),
        MultiFieldPanel(
            [
                FieldPanel("button_text"),
                FieldPanel("button_url"),
                FieldPanel("button_display"),
                FieldPanel("button_styling"),
            ],
            heading="Button (optional)",
        ),
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

