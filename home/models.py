import datetime
import re
import uuid
from os.path import splitext


from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_slug
from django.db import models
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.utils.formats import date_format
from django.utils.safestring import mark_safe
from django.utils import timezone
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
from wagtail.contrib.forms.forms import BaseForm, FormBuilder, SelectDateForm

from wagtail.contrib.forms.models import AbstractEmailForm, AbstractFormField, AbstractFormSubmission, FORM_FIELD_CHOICES
from wagtail.contrib.forms.views import SubmissionsListView

from wagtail.fields import RichTextField
from wagtail.images.fields import WagtailImageField
from wagtail.images import get_image_model

from wagtail.models import (
    Collection,
    DraftStateMixin,
    Orderable,
    Page,
    PreviewableMixin,
    RevisionMixin,
    TranslatableMixin,
)
from wagtail.contrib.forms.utils import get_field_clean_name

from wagtailcaptcha.forms import remove_captcha_field
from wagtailcaptcha.models import WagtailCaptchaEmailForm, WagtailCaptchaFormBuilder

from encrypted_json_fields.fields import EncryptedJSONField, EncryptedCharField, EncryptedEmailField

from common.fields import data_processing_consent_field
from payments.utils import get_paypal_form
from .generate_form_submission_pdf import generate_pdf


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
    For standard non-draft-savable forms e.g. contact form
    https://docs.wagtail.org/en/stable/reference/contrib/forms/index.html
    """

    page = ParentalKey('FormPage', related_name='form_fields', on_delete=models.CASCADE)


class EmailFormBuilder(FormBuilder):           

    @property
    def formfields(self):
        formfields = super().formfields
        original_formfields = set(formfields)

        fields_to_add = {}
        # Check for any of the usual personal data fields
        if original_formfields & {"name", "email", "email_address", "address", "phone", "phone_number"}:
            if "data_processing_consent" not in original_formfields:
                formfields["data_processing_consent"] = data_processing_consent_field()
        formfields = {
            **fields_to_add,
            **formfields
        }
        return formfields

    def get_form_class(self):
        return type("WagtailForm", (BaseForm,), self.formfields)


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
        ref =  getattr(self, "ref", None)
        if ref and "subject" in form.fields:
            form.fields["subject"].initial = f"Enquiry about {ref}"
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


class PDFBaseForm(BaseForm):

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.reference:
            # Add a hidden field with the reference
            self.fields["reference"] = forms.CharField(
                widget=forms.HiddenInput(), required=False,
                initial=self.instance.reference
            )

    def clean(self, submit=False):
        if submit:
            for field in self.fields:
                if not self.cleaned_data.get(field):
                    self.add_error(field, "This field is required")


class PDFFormBuilder(FormBuilder):           

    @property
    def formfields(self):
        formfields = super().formfields
        original_formfields = set(formfields)

        fields_to_add = {}
        if "name" not in original_formfields:
            fields_to_add["name"] = forms.CharField()
        if not (original_formfields & {"email", "email_address"}):
            fields_to_add["email"] = forms.EmailField()
        if "data_processing_consent" not in original_formfields:
            fields_to_add["data_processing_consent"] = data_processing_consent_field()
        formfields = {
            **fields_to_add,
            **formfields
        }
        return formfields

    def get_form_class(self):
        return type("WagtailForm", (PDFBaseForm,), self.formfields)


class OrderingMixin:

    def _get_order_label(self, ordering_by_field, field):
        order = ordering_by_field.get(field)
        return order[1] if order else "orderable"


class PDFFormSubmissionsListView(OrderingMixin, SubmissionsListView):
    # Template shows name/email/submission date and link to PDF/page
    template_name = "home/pdf_list_submissions_index.html"

    orderable_fields = (
        "id",
        "submit_time",
        "name",
        "email",
        "reference",
    )
    
    def _export_headings(self):
        self.list_export += ["reference", "status"]
        self.export_headings.update(
            {
                "reference": "Reference",
                "status": "Status",
            }
        )

    def stream_csv(self, queryset):
        self._export_headings()
        return super().stream_csv(queryset)

    def write_xlsx(self, queryset, output):
        self._export_headings()
        return super().write_xlsx(queryset, output)

    def to_row_dict(self, item):
        """Orders the submission dictionary for spreadsheet writing"""
        row_dict = super().to_row_dict(item)
        row_dict["reference"] = item.reference
        row_dict["status"] = item.status
        return row_dict

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        if not self.is_export:
            # We want submit time, name, email (from the submission, not the form), 
            # and our extra fields
            ordering_by_field = self.get_validated_ordering()
            
            context_data["data_headings"] = [
                context_data["data_headings"][0],
                {"name": "name", "label": "Name", "order": self._get_order_label(ordering_by_field, "name")},
                {"name": "form_data__email", "label": "Email", "order": self._get_order_label(ordering_by_field, "email")},
                {"name": "reference", "label": "Reference", "order": self._get_order_label(ordering_by_field, "reference")},
                {'name': 'status', 'label': 'Status', 'order': None},
                {'name': 'download', 'label': 'Download', 'order': None},
                {'name': 'view', 'label': 'View', 'order': None},
            ]

            submissions = PDFFormSubmission.objects.filter(
                id__in=[row["model_id"] for row in context_data["data_rows"]]
            )
            submission_data = {
                sub.id: [
                    sub.name, 
                    sub.email, 
                    sub.reference, 
                    sub.status,
                    mark_safe(f"<a href={reverse('pdf_form_download', args=(sub.pk,))}>Download</a>"),
                    mark_safe(f"<a href={sub.get_absolute_url()}>View</a>")
                ] for sub in submissions
            }
            
            for row in context_data["data_rows"]:
                row["fields"] = [
                    row["fields"][0], *submission_data[row["model_id"]], 
                ]

        return context_data


class PDFFormField(AbstractFormField):
    """
    For editable forms that are sent as PDF e.g. adoption application form:
    https://docs.wagtail.org/en/stable/reference/contrib/forms/index.html
    """

    page = ParentalKey("PDFFormPage", related_name="pdf_form_fields", on_delete=models.CASCADE)
    before_info_text = RichTextField(blank=True)
    after_info_text = RichTextField(blank=True)
    required_for_draft = models.BooleanField(default=False, help_text="Required in order to save as draft")

    panels = panels = [
        FieldPanel("label"),
        FieldPanel("help_text"),
        FieldPanel("before_info_text"),
        FieldPanel("after_info_text"),
        FieldPanel("required_for_draft"),
        FieldPanel("field_type", classname="formbuilder-type"),
        FieldPanel("choices", classname="formbuilder-choices"),
        FieldPanel("default_value", classname="formbuilder-default"),
    ]
    def save(self, *args, **kwargs):
        self.required = self.required_for_draft
        super().save(*args, **kwargs)


class PDFFormPage(FormPage):

    form_builder = PDFFormBuilder
    submissions_list_view_class = PDFFormSubmissionsListView
    
    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("image"),
        FieldPanel("body"),
        InlinePanel("pdf_form_fields", heading="Form fields", label="Field"),
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

    def get_submission_class(self):
        return PDFFormSubmission

    def get_form_fields(self):
        return self.pdf_form_fields.all()

    def get_form_parameters(self):
        params = super().get_form_parameters()
        return {**params, "page": self}

    @property
    def required_for_draft_fields(self):
        return [
            "reference", "name", "email", "email_address", "data_processing_consent"
            *[field.clean_name for field in self.get_form_fields() if field.required_for_draft]
        ]

    @property
    def form_field_info_texts(self):
        return {
            field.label: {
                "before": field.before_info_text, 
                "after": field.after_info_text
            } for field in self.get_form_fields()
        }

    def serve(self, request, *args, **kwargs):
        if request.method == "POST":
            # Is it a save-for-later POST?
            save_as_draft = "save_as_draft" in request.POST
            reference = request.POST.get("reference")
            instance = None
            if reference:
                try:
                    instance = self.pdfformsubmission_set.get(reference=reference)
                except PDFFormSubmission.DoesNotExist:
                    ...
            form = self.get_form(
                request.POST, request.FILES, instance=instance, user=request.user,
            )
            if form.is_valid():                
                form_submission, form = self.process_form_submission(form, save_as_draft=save_as_draft)
                if save_as_draft:
                    form = self.get_form(instance=form_submission, user=request.user, initial=request.POST)
                    messages.success(request, "Draft saved!")
                    context = self.get_context(request)
                    context["form"] = form
                    return TemplateResponse(request, self.get_template(request), context)
                else:
                    if form.is_valid():
                        messages.success(
                            request, 
                            "Your form has been submitted successfully. A member of our team "
                            "will be in touch shortly. "
                        )
                        return redirect(form_submission.get_absolute_url_with_token())
        else:
            reference = request.GET.get("reference")
            instance = None
            initial = {}
            if reference:
                try:
                    instance = self.pdfformsubmission_set.get(reference=reference)
                    initial=instance.form_data
                except PDFFormSubmission.DoesNotExist:
                    ...
            if instance:
                token = request.GET.get("token")
                token_qs = f"?token={token}" if token else ""
                if not instance.is_draft:
                    # Can't edit if it's not draft
                    return redirect(instance.get_absolute_url() + token_qs)
                # skip token check if user is logged in AND is the author of this
                # submission
                if request.user.is_authenticated and (request.user.email == instance.email):
                    ...
                else:
                    # Can access if token is valid, even if it's expired
                    if not instance.token_valid(token):
                        return redirect(instance.get_absolute_url() + token_qs)
            form = self.get_form(instance=instance, user=request.user, initial=initial)

        context = self.get_context(request)
        context["form"] = form
        return TemplateResponse(request, self.get_template(request), context)

    def render_save_draft_email_for_user(self, submission):
        content = "{self.title}\n======================="
        content = "Your form has been saved.\n"
        content += f"\n\nYou can view and edit your responses at https://{settings.DOMAIN}{submission.get_absolute_url_with_token()}."
        return content
    
    def render_email_for_user(self, submission):
        content = "{self.title}\n======================="
        content = "Thank you for submitting your form. A member of our team will be in touch shortly\n"
        content += f"You can view your responses at https://{settings.DOMAIN}{submission.get_absolute_url()}."
        return content
    
    def render_email(self, form):
        # form is a PDFFormSubmission instance
        content = f"A {self.title} submission has been received from {form.name} ({form.email}) (PDF copy attached)."
        return content
    
    def send_mail_to_admin(self, submission):
         addresses = [x.strip() for x in self.to_address.split(",")]
         self.send_mail_with_pdf(
            submission, 
            self.subject,  
            self.render_email(submission), 
            addresses, 
            self.from_address, 
            [submission.email]
        )

    def send_mail_to_user(self, submission, subject, content):
        send_mail(
            subject,
            content,
            [submission.email], 
            from_email=settings.DEFAULT_FROM_EMAIL, 
            reply_to=[settings.DEFAULT_ADMIN_EMAIL]
        )
        
    def send_mail_with_pdf(
            self, 
            submission, 
            subject, 
            content, 
            to_addresses, 
            from_address, 
            reply_to_addresses
        ):
        # form is a PDFFormSubmission instance
        kwargs = {
            "headers": {
                "Auto-Submitted": "auto-generated",
            },
            "reply_to": reply_to_addresses,
        }

        mail = EmailMultiAlternatives(
            subject, content, from_address, to_addresses, **kwargs
        )
        pdf = generate_pdf(submission)
        mail.attach(submission.get_download_filename(), pdf.read())
        return mail.send()

    def process_form_submission(self, form, save_as_draft=True):
        """
        Accepts form instance with submitted data, user and page.
        Creates submission instance.

        If save_as_draft, send an email to the user with a link to
        their editable form. Save the submission but don't send 
        usual emails. 
        """
        if form.instance:
            new = False
            submission = form.instance
            submission.form_data = form.cleaned_data
            submission.save()
        else:
            submission = self.get_submission_class().objects.create(
                form_data=form.cleaned_data,
                page=self,
            )
            new = True
        
        if save_as_draft:
            if new:
                # Send email to user if this is the first time the draft is saved
                # Don't sent repeated emails for each save
                self.send_mail_to_user(
                    submission, 
                    subject=f"{self.subject} has been saved", 
                    content=self.render_save_draft_email_for_user(submission),
                )
        else:
            form.clean(submit=True)
            if not form.is_valid():
                return submission, form

            submission.is_draft = False
            submission.submit_time = timezone.now()
            submission.save()
            submission.reset_token()
            # Send admin email with PDF
            if self.to_address:
                self.send_mail_to_admin(submission)
            # send email to user
            self.send_mail_to_user(
                submission, 
                f"{self.subject} has been submitted",
                content=self.render_email_for_user(submission),
            )    
        return submission, form


class PDFFormSubmission(AbstractFormSubmission):
    reference = ShortUUIDField(
        editable = False
    )
    form_data = EncryptedJSONField(encoder=DjangoJSONEncoder)
    is_draft = models.BooleanField(default=True)

    name = EncryptedCharField(blank=True)
    email = EncryptedEmailField(blank=True)

    token = models.UUIDField(null=True)
    token_expiry = models.DateTimeField(null=True)

    @property
    def form_page(self):
        return self.page.specific
    
    def email_from_form_data(self):
        email_field = next((k for k in self.form_data if k in ["email", "email_address"]))
        return self.form_data[email_field]

    def name_from_form_data(self):
        return self.form_data["name"]

    @property
    def status(self):
        if self.is_draft:
            return "Draft"
        return "Submitted"

    def reset_token(self):
        self.token = uuid.uuid4()
        self.token_expiry = timezone.now() + datetime.timedelta(seconds=60*15)
        self.save()
    
    def token_valid(self, token):
        """Token is current (but could be expired)"""
        return self.token is not None and str(token) == str(self.token)
    
    def token_active(self, token):
        """Token is current and has not expired"""
        return self.token_valid(token) and self.token_expiry > timezone.now()

    def display_data(self):
        def _format_key(key):
            try:
                return self.form_page.pdf_form_fields.get(clean_name=key).label
            except PDFFormField.DoesNotExist:
                return key

        def _format_value(value):
            if value is None:
                return ""
            if isinstance(value, list):
                value = ", ".join([str(v) for v in value])
            
            try:
                return (
                    datetime.datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
                )
            except (ValueError, TypeError):
                ...
        
            formatted_value = {
                True: "Confirmed",
                False: "Not answered"
            }.get(value, str(value))
            formatted_value = formatted_value.replace("\r\n", "\n")
            return formatted_value

        fields_in_order = self.form_page.pdf_form_fields.exclude(
            clean_name__in=["name", "email", "email_address", "wagtailcaptcha", "reference"]
            ).values_list("clean_name", flat=True)
        valid_fields = [field for field in  fields_in_order if field in self.form_data]

        return {
            _format_key(field): _format_value(self.form_data[field]) for field in valid_fields
        }

    def get_download_filename(self):
        return f"{self.page.slug}-{self.name.replace(' ', '-')}-{self.reference}.pdf"
    
    def get_absolute_url(self):
        return reverse("pdf_form_detail", kwargs={"reference": self.reference})

    def get_absolute_url_with_token(self):
        return self.get_absolute_url() + f"?token={self.token}"

    def get_request_token_url(self):
        return reverse(
            "pdf_form_token_request", 
            kwargs={"reference": self.reference}
        )

    def save(self, *args, **kwargs):
        is_new = not self.id
        self.name = self.name_from_form_data()
        self.email = self.email_from_form_data()
        super().save(*args, **kwargs)
        if is_new:
            self.reset_token()
    

class OrderFormField(AbstractFormField):
    """
    https://docs.wagtail.org/en/stable/reference/contrib/forms/index.html
    """
    page = ParentalKey("OrderFormPage", related_name="order_form_fields", on_delete=models.CASCADE)

    field_type = models.CharField(
        verbose_name='field type',
        max_length=16,
        choices=list(FORM_FIELD_CHOICES) + [('image', 'Upload Image')]
    )

    def get_field_clean_name(self):
        # if clean name is already set, just return it
        if self.clean_name:
            return self.clean_name
        return get_field_clean_name(self.label)


class ProductVariant(Orderable):
    page = ParentalKey("OrderFormPage", related_name="product_variants", on_delete=models.CASCADE)
    group_name = models.CharField(
        max_length=100, blank=True, 
        help_text="Optional group for this variant. Use to group variants with multiple options, e.g. sizes"
    )
    group_total_available = models.PositiveIntegerField(null=True, blank=True)
    variant_total_available = models.PositiveIntegerField(null=True, blank=True)
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
    default_value = models.PositiveIntegerField(default=0)
    slug = models.CharField(max_length=60, blank=True, default="", help_text="This field will be autopoulated")
    
    def save(self, *args, **kwargs):
        if self.page.specific.total_available and (self.group_total_available or self.variant_total_available):
            raise ValueError("Cannot set group/variant stock for a page with overall stock set")
        if self.group_total_available and not self.group_name:
            raise ValueError("Group stock requires a group name")
        if self.group_total_available and self.variant_total_available:
            raise ValueError("Cannot set both group and product stock")

        if not self.slug:
            base_slug = "pv__"
            if self.group_name:
                base_slug += f"{get_field_clean_name(self.group_name)}_"
            base_slug += get_field_clean_name(self.name)
            slug = base_slug
            counter = 0
            while ProductVariant.objects.filter(page=self.page, slug=slug).exclude(id=self.id).exists():
                counter += 1
                slug = f"{base_slug}_{counter}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def group_and_name(self):
        if self.group_name:
            return f"{self.group_name} - {self.name}"
        return self.name


class OrderSubmissionsFilterForm(SelectDateForm):
    status = forms.ChoiceField(
        choices=(("---", ""), ("paid", "paid"), ("shipped", "shipped"), ("not_paid", "not paid"), ("not_shipped", "not shipped")),
        required=False,
        initial="---"
    )


class OrderFormSubmissionsListView(OrderingMixin, SubmissionsListView):

    template_name = "home/order_list_submissions_index.html"

    orderable_fields = (
        "id",
        "submit_time",
        "form_data__email",
        "form_data__name",
        "reference",
        "shipped",
        "paid",
    )

    def _export_headings(self):
        self.list_export += ["email", "reference", "total", "total_items", "paid", "shipped"]
        self.export_headings = {
            k: self._get_heading_label(k, v) for k, v in self.export_headings.items()
        }
        self.export_headings.update(
            {   
                "email": "Email",
                "reference": "Reference",
                "total": "Total (£)", 
                "total_items": "Total items", 
                "paid": "Paid", 
                "shipped": "Shipped"
            }
        )

    def get_filtering(self):
        """
        Return filering as a dict for submissions queryset
        This is identical to the base class, except that we substitute our
        OrderSubmissionsFilterForm to add in the extra status field.
        """
        self.select_date_form = OrderSubmissionsFilterForm(self.request.GET)
        result = {}
        if self.select_date_form.is_valid():
            date_from = self.select_date_form.cleaned_data.get("date_from")
            date_to = self.select_date_form.cleaned_data.get("date_to")
            status = self.select_date_form.cleaned_data.get("status")
            if date_to:
                # careful: date_to must be increased by 1 day
                # as submit_time is a time so will always be greater
                date_to += datetime.timedelta(days=1)
                if date_from:
                    result["submit_time__range"] = [date_from, date_to]
                else:
                    result["submit_time__lte"] = date_to
            elif date_from:
                result["submit_time__gte"] = date_from

            match status:
                case "paid":
                    result["paid"] = True
                case "not_paid":
                    result["paid"] = False
                case "shipped":
                    result["shipped"] = True
                case "not_shipped":
                    result["shipped"] = False

        return result
    
    def stream_csv(self, queryset):
        self._export_headings()
        return super().stream_csv(queryset)

    def write_xlsx(self, queryset, output):
        self._export_headings()
        return super().write_xlsx(queryset, output)

    def to_row_dict(self, item):
        """Orders the submission dictionary for spreadsheet writing"""
        row_dict = super().to_row_dict(item)
        row_dict["reference"] = item.reference
        row_dict["total"] = item.cost
        row_dict["total_items"] = self.form_page.quantity_ordered_by_submission(row_dict)["total"]
        row_dict["paid"] = "Y" if item.paid else "-"
        row_dict["shipped"] = "Y" if item.shipped else "-"
        return row_dict

    def _get_heading_label(self, slug, name):
        try:
            pv = ProductVariant.objects.get(page=self.form_page, slug=slug)
            return pv.group_and_name
        except ProductVariant.DoesNotExist:
            return name
    
    def get_context_data(self, **kwargs):
        ordering_by_field = self.get_validated_ordering()
        context_data = super().get_context_data(**kwargs)
        if not self.is_export:
            
            ordered = self.form_page.get_total_quantity_ordered_by_group_and_variant()
            totals_available = self.form_page.get_stock_quantities()
            
            context_data["description"] = f"Total sold: {ordered['total']} | Remaining stock: N/A"

            if totals_available.get("overall"):
                total_ordered = ordered["total"]
                remaining_stock = totals_available["overall"] - total_ordered
                context_data["description"] = f"Total sold: {total_ordered} | Remaining stock: {remaining_stock}"
            else:
                stock_desc = []
                for group_name, total_available in totals_available["groups"].items():
                    ordered_for_group = ordered["groups"].get(group_name, 0)
                    stock_desc.append(f"{group_name}: sold {ordered_for_group}/{total_available}")
                
                for variant_slug, total_available in totals_available["variants"].items():
                    ordered_for_variant = ordered["variants"].get(variant_slug, 0)
                    stock_desc.append(f"{variant_slug}: sold {ordered_for_variant}/{total_available}")

                if stock_desc:
                    context_data["description"] = " | ".join(stock_desc)

            def _reformat_field(heading):
                heading["label"] = self._get_heading_label(heading["name"], heading["label"])
                if heading["name"] in ["name", "email", "email_address"]:
                    form_data_name = f"form_data__{heading['name']}"
                    heading["name"] = form_data_name
                    heading["order"] = self._get_order_label(ordering_by_field, form_data_name)
                return heading
        
            data_headings = [
                _reformat_field(heading) for heading in context_data["data_headings"]
            ]

            email_from_form = {data_heading["name"] for data_heading in data_headings} & {"form_data__email", "form_data__email_address"}
            if not email_from_form:
                data_headings.append(
                    {"name": "form_data__email", "label": "Email", "order": self._get_order_label(ordering_by_field, "form_data__email")}
                )
            data_headings.extend([
                {'name': 'total_items', 'label': 'Total items', 'order': None},
                {'name': 'total', 'label': 'Total (£)', 'order': None},
                {"name": "reference", "label": "Reference", "order": self._get_order_label(ordering_by_field, "reference")},
                {'name': 'paid', 'label': 'Paid', 'order': self._get_order_label(ordering_by_field, "paid")},
                {'name': 'shipped', 'label': 'Shipped', 'order': self._get_order_label(ordering_by_field, "shipped")},
            ])

            context_data["data_headings"] = data_headings

            fields = self.form_page.get_data_fields()

            submissions = OrderFormSubmission.objects.filter(
                id__in=[row["model_id"] for row in context_data["data_rows"]]
            )
            submission_data = {
                submission.id: {
                    "total": submission.cost,
                    "reference": submission.reference,
                    "email": submission.email,
                    "paid": "Y" if submission.paid else "-",
                    "shipped": "Y" if submission.shipped else "-",
                } for submission in submissions
            }

            for row in context_data["data_rows"]:
                form_data = row["fields"]
                form_data_dict = {field[0]: form_data[i] for i, field in enumerate(fields)}
                total_items = self.form_page.quantity_ordered_by_submission(form_data_dict)["total"]
                email = submission_data[row["model_id"]].pop("email")
                if not email_from_form:
                    form_data.append(email)
                extra_form_data = [total_items, *submission_data[row["model_id"]].values()]
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
    one_time_use = models.BooleanField(default=True)

    class Meta:
        unique_together = ("order_form_page", "code")


class OrderBaseForm(BaseForm):

    def clean(self):
        super().clean()
        voucher_code = self.cleaned_data.get("voucher_code", "").strip()
        if (
            voucher_code and 
            voucher_code not in 
            self.page.voucher_codes.filter(code=voucher_code, active=True).values_list("code", flat=True)
        ):
            del self.cleaned_data["voucher_code"]

        total_items = self.page.quantity_ordered_by_submission(self.cleaned_data)["total"]
        if total_items == 0:
            self.add_error("__all__", "Select at least one item")

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

        if not (set(original_fields) & {"email", "email_address"}):
            original_fields = {
                "email": forms.EmailField(),
                **original_fields
            }
        if "data_processing_consent"  not in original_fields:
            original_fields.update(
                data_processing_consent=data_processing_consent_field()
            )
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

    def create_image_field(self, field, options):
        return WagtailImageField(**options)

    def get_form_class(self):
        return type("WagtailForm", (OrderBaseForm,), self.formfields)


class OrderShippingCost(Orderable):
    DEFAULT_MAX = 999999999
    order_form_page = ParentalKey("OrderFormPage", related_name="shipping_costs", on_delete=models.CASCADE)
    max_quantity = models.PositiveIntegerField(default=DEFAULT_MAX)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ("max_quantity",)
        unique_together = ("order_form_page", "max_quantity")


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
    total_available = models.PositiveIntegerField(
        null=True, blank=True, help_text="Max total number available (optional)"
    )
    show_summary = models.BooleanField(
        default=False,
        help_text="Show a summary of order options before form."
    )

    uploaded_image_collection = models.ForeignKey(
        'wagtailcore.Collection',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    form_footer_text = RichTextField(blank=True)
    thank_you_text = RichTextField(blank=True)
    

    # Note how we include the FormField object via an InlinePanel using the
    # related_name value
    content_panels = AbstractEmailForm.content_panels + [
        FieldPanel("image"),
        FieldPanel("inline_image"),
        FieldPanel("body"),
        FieldPanel("show_summary"),
        MultiFieldPanel(
            [
                FieldPanel("product_name"),
                FieldPanel("product_description"),
                FieldPanel("total_available"),
                InlinePanel(
                    "shipping_costs", label="Shipping Costs", 
                    panels=[
                        FieldPanel("max_quantity", help_text="Max quantity this rate applies to. Default ceiling value is 999999999"),
                        FieldPanel("amount"),
                    ]
                ),
                InlinePanel(
                    "product_variants", label="Product Variants", 
                    panels=[
                        FieldPanel("group_name"),
                        FieldPanel("group_total_available"),
                        FieldPanel("variant_total_available"),
                        FieldPanel("name"),
                        FieldPanel("description"),
                        FieldPanel("cost"),
                        FieldPanel("item_count"),
                        FieldPanel("quantity_choices"),
                        FieldPanel("default_value"),
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
        FieldPanel('uploaded_image_collection'),
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
                        FieldPanel("one_time_use"),
                        FieldPanel("active"),
                    ]
                ),
            ],
            "Voucher codes",
        )
    ]

    end_of_form_field_names = ["wagtailcaptcha", "voucher_code"]
    subpage_types = []
    
    def get_uploaded_image_collection(self):
        """
        Returns a Wagtail Collection, using this form's saved value if present,
        otherwise returns the 'Root' Collection.
        """
        collection = self.uploaded_image_collection
        return collection or Collection.get_first_root_node()

    @staticmethod
    def get_image_title(filename):
        """
        Generates a usable title from the filename of an image upload.
        Note: The filename will be provided as a 'path/to/file.jpg'
        """

        if filename:
            result = splitext(filename)[0]
            result = result.replace('-', ' ').replace('_', ' ')
            return result.title()
        return ''

    def save(self, *args, **kwargs):
        self.from_address = settings.DEFAULT_FROM_EMAIL
        super().save(*args, **kwargs)

        # Check the product variant stock
        all_groups = set(self.product_variants.filter(group_total_available__isnull=False).values_list("group_name", flat=True))
        for group_name in all_groups:
            group_stock = {
                stock for stock in set(self.product_variants.filter(group_name=group_name).values_list("group_total_available", flat=True))
                if stock not in [None, ""]
            }
            if len(group_stock) != 1:
                raise ValueError("Group stock inconsistent across product variants")
        
        # Save the product variants to ensure slugs have been generated
        for pr in self.product_variants.all():
            pr.save()
        # generate/update quantity fields
        for slug in self.product_variant_slugs:
            self.create_or_update_order_form_field(slug)
        fields_to_remove = self.product_quantity_field_names - self.product_variant_slugs
        for field_name in fields_to_remove:
            self.order_form_fields.get(clean_name=field_name).delete()      

    @property
    def subject_title(self):
        title = re.sub(r"Order Form", "", self.title, flags=re.IGNORECASE)
        title = title.strip()
        return title

    @property
    def shipping_costs_dict(self):
        if self.shipping_costs.exists():
            sc_dict = {}
            previous_max_quantity = None
            for sc in self.shipping_costs.all():
                if sc.max_quantity ==  1:
                    label = f"1 item"
                elif sc.max_quantity == OrderShippingCost.DEFAULT_MAX:
                    if previous_max_quantity is not None:
                        label = f"{previous_max_quantity + 1}+ items"
                    else:
                        label = "Flat rate per order"
                elif previous_max_quantity is None:
                        label = f"1-{sc.max_quantity} items"
                else:
                    label = f"{previous_max_quantity + 1}-{sc.max_quantity} items"
                sc_dict[sc.max_quantity] = (label, sc.amount)
                previous_max_quantity = sc.max_quantity
            return sc_dict

    def get_shipping_cost(self, quantity):
        if not self.shipping_costs_dict:
            return 0
        for max_quantity, shipping_label_and_cost in self.shipping_costs_dict.items():
            if max_quantity >= quantity:
                return shipping_label_and_cost[1]
        # If there was no ceiling max set, use the highest rate
        return shipping_label_and_cost[1]

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
                default_value = variant.default_value
            )
        if (field.choices != variant.quantity_choices) or (field.label != variant.name): 
            field.choices = variant.quantity_choices
            field.label = variant.name
            field.save()

    def variants_by_group(self):
        groups = self.product_variants.values_list("group_name", flat=True)
        # remove duplicates but preserve order
        groups = list(dict.fromkeys(groups))
        return {
            group_name: self.product_variants.filter(group_name=group_name) for group_name in groups
        }

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
                quantity = v[0]
            else:
                quantity = v
            # Quantity may be None if new variants have been added
            if quantity is None:
                return 0
            return int(quantity)     
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
            # shipping cost
            total_quantity = self.quantity_ordered_by_submission(data)["total"]
            total += self.get_shipping_cost(total_quantity)
            total -= voucher_amount

        return variant_quantities, total, voucher_amount

    def _item_counts_per_variant(self):
        return dict(self.product_variants.values_list("slug", "item_count"))

    def sold_out(self):
        # Are we sold out entirely?
        if not self.id:
            return False
        if self.total_available:
            return self.get_total_quantity_ordered() >= self.total_available
        
        totals_available = self.get_stock_quantities()
        ordered = self.get_total_quantity_ordered_by_group_and_variant()

        if not (totals_available["groups"] or totals_available["variants"]):
            return False

        for group_name, total_available in totals_available["groups"].items():
            if total_available > ordered["groups"].get(group_name, 0):
                return False
        
        for variant_slug, total_available in totals_available["variants"].items():
            if total_available > ordered["variants"].get(variant_slug, 0):
                return False
        
        return True

    def disallowed_variants(self):
        item_counts_per_variant = self._item_counts_per_variant()
        if self.total_available:
            quantity_ordered_so_far = self.get_total_quantity_ordered()
            remaining_stock = self.total_available - quantity_ordered_so_far 
            return [
                variant for variant in self.product_variants.all()
                if item_counts_per_variant[variant.slug] > remaining_stock
            ]
        
        disallowed = []
        totals_available = self.get_stock_quantities()
        ordered = self.get_total_quantity_ordered_by_group_and_variant()

        for variant in self.product_variants.all():
            if variant.group_name in totals_available["groups"]:
                remaining_stock = totals_available["groups"][variant.group_name] - ordered["groups"].get(variant.group_name, 0)
                if item_counts_per_variant[variant.slug] > remaining_stock:
                    disallowed.append(variant)
            elif variant.slug in totals_available["variants"]:
                remaining_stock = totals_available["variants"][variant.slug] - ordered["variants"].get(variant.slug, 0)
                if item_counts_per_variant[variant.slug] > remaining_stock:
                    disallowed.append(variant)

        return disallowed

    def get_total_quantity_ordered(self):
        total = 0
        if self.pk:
            submissions = self.orderformsubmission_set.all()
            item_counts_per_variant = self._item_counts_per_variant()
            
            for submission in submissions:
                total += self.quantity_ordered_by_submission(submission.form_data, item_counts_per_variant)["total"]
        return total

    def get_total_quantity_ordered_by_group_and_variant(self):
        quantities_ordered ={
            "total": 0,
            "groups": {},
            "variants": {}
        }
        if self.pk:
            submissions = self.orderformsubmission_set.all()
            item_counts_per_variant = self._item_counts_per_variant()

            for submission in submissions:
                submission_quantities_ordered = self.quantity_ordered_by_submission(submission.form_data, item_counts_per_variant)
                quantities_ordered["total"] += submission_quantities_ordered["total"]
                for group, quantity in submission_quantities_ordered["groups"].items():
                    quantities_ordered["groups"].setdefault(group, 0)
                    quantities_ordered["groups"][group] += quantity
                for variant, quantity in submission_quantities_ordered["variants"].items():
                    quantities_ordered["variants"].setdefault(variant, 0)
                    quantities_ordered["variants"][variant] += quantity

        return quantities_ordered
    
    def get_stock_quantities(self):
        if self.total_available:
            return {"overall": self.total_available}
        groups_with_totals = self.product_variants.filter(group_total_available__isnull=False).values_list("group_name", "group_total_available")
        totals = {"groups": {}, "variants": {}}
        for group_name, group_total in groups_with_totals:
            totals["groups"][group_name] = group_total
        variants_with_totals = self.product_variants.filter(variant_total_available__isnull=False).values_list("slug", "variant_total_available")
        for variant_slug, variant_total in variants_with_totals:
            totals["variants"][variant_slug] = variant_total
        return totals

    def quantity_ordered_by_submission(self, form_data, item_counts_per_variant=None):
        variant_to_group = dict(self.product_variants.all().values_list("slug", "group_name"))
        quantities = {
            "total": 0,
            "groups": {},
            "variants": {}
        }

        if item_counts_per_variant is None:
            item_counts_per_variant = self._item_counts_per_variant()
        variant_quantities = self._get_quantities(form_data)

        for key, quantity in variant_quantities.items():
            quantities["total"] += item_counts_per_variant[key] * quantity
            quantities["variants"].setdefault(key, 0)
            quantities["variants"][key] += item_counts_per_variant[key] * quantity
            quantities["groups"].setdefault(variant_to_group[key], 0)
            quantities["groups"][variant_to_group[key]] += item_counts_per_variant[key] * quantity
        return quantities

    def quantity_submitted_is_valid(self, form_data):
        validation_error_msg = ""
        valid = True

        total_for_this_order = self.quantity_ordered_by_submission(form_data)

        # First check totals
        if self.total_available:
            total_ordered_so_far = self.get_total_quantity_ordered()
            remaining_stock = self.total_available - total_ordered_so_far
            valid = total_for_this_order["total"] <= remaining_stock
            if not valid:
                rem_stock = remaining_stock if remaining_stock >= 0 else 0
                validation_error_msg  = f"Quantity selected is unavailable; select a maximum of {rem_stock} total items."
            return valid, validation_error_msg
        

        total_ordered_so_far = self.get_total_quantity_ordered_by_group_and_variant()
        totals_available = self.get_stock_quantities()

        # Next check groups
        for group, quantity in total_for_this_order["groups"].items():
            if group in totals_available["groups"]:
                remaining_stock = totals_available["groups"][group] - total_ordered_so_far["groups"].get(group, 0)
                valid = quantity <= remaining_stock
                if not valid:
                    rem_stock = remaining_stock if remaining_stock >= 0 else 0
                    validation_error_msg  = f"Quantity selected for {group} is unavailable; select a maximum of {rem_stock} total items."
                    return valid, validation_error_msg
        
        # Finally check variants
        for variant, quantity in total_for_this_order["variants"].items():
            if variant in totals_available["variants"]:
                remaining_stock = totals_available["variants"][variant] - total_ordered_so_far["variants"].get(variant, 0)
                valid = quantity <= remaining_stock
                if not valid:
                    rem_stock = remaining_stock if remaining_stock >= 0 else 0
                    variant_name = self.product_variants.get(slug=variant).name
                    validation_error_msg  = f"Quantity selected for {variant_name} is unavailable; select a maximum of {rem_stock} total items."
                    return valid, validation_error_msg

        return valid, validation_error_msg

    def _render_extra_email(self,  submission, total, discount):
        content = "\nOrder summary:\n"
        content += "\n".join([f"  - {variant.group_and_name} ({quantity})" for variant, quantity in submission.items_ordered()])
        content += f"\n\nTotal items ordered: {self.quantity_ordered_by_submission(submission.form_data)['total']}"
        if discount:
            content += f"\nDiscount: £{discount}"
        content += f"\nTotal amount due: £{total}"
        return content

    def render_email(self, form, submission, total, discount):
        # Everything here is identical to the base class, except we
        # skip andy fields that are product variants, and render them
        # in the order summary at the end
        content = []

        cleaned_data = form.cleaned_data
        for field in form:
            if field.name not in cleaned_data:
                continue
            if field.name in self.product_quantity_field_names:
                continue

            value = cleaned_data.get(field.name)

            if isinstance(value, list):
                value = ", ".join(value)

            # Format dates and datetime(s) with SHORT_DATE(TIME)_FORMAT
            if isinstance(value, datetime.datetime):
                value = date_format(value, settings.SHORT_DATETIME_FORMAT)
            elif isinstance(value, datetime.date):
                value = date_format(value, settings.SHORT_DATE_FORMAT)
            
            if field.name == "data_processing_consent":
                value = "confirmed"

            content.append(f"{field.label}: {value}")

        content = "\n".join(content)
        content += "\n"
        content += self._render_extra_email(submission, total, discount)
        return content

    def render_email_for_purchaser(self, submission, total, discount):
        content = "Thank you for your order!\n"
        content += self._render_extra_email(submission, total, discount)
        content += f"\n\nView your order at https://{settings.DOMAIN}{submission.get_absolute_url()}."
        content += f"\nIf you haven't made your payment yet, you'll also find a link there."
        return content
    
    def render_landing_page(self, request, form_submission=None, *args, **kwargs):
        context = self.get_context(request)
        context["form_submission"] = form_submission
        _, total, _ = self.get_variant_quantities_and_total(form_submission.get_data())
        
        context["total"] = total
        total_quantity = self.quantity_ordered_by_submission(form_submission.form_data)['total']
        shipping = self.get_shipping_cost(total_quantity)
        context["paypal_form"] = get_paypal_form(
            request=request,
            amount=total - shipping, 
            item_name=f"Website order: {self.title} ({total_quantity} item{'s' if total_quantity > 0 else ''})",
            reference=form_submission.reference,
            shipping=shipping,
        )
        return TemplateResponse(
            request, self.get_landing_page_template(request), context
        )

    def get_submission_class(self):
        return OrderFormSubmission

    def send_mail(self, form, submission, total, discount, subject):
        addresses = [x.strip() for x in self.to_address.split(",")]
        send_mail(
            subject,
            self.render_email(form, submission, total, discount),
            addresses,
            self.from_address,
        )

    def get_context(self, request):
        context = super().get_context(request)
        if request.GET.get("order_ref"):
            context["existing_order_ref"] = request.GET["order_ref"]
        else:
            existing_order_ref = request.session.get("orders", {}).get(str(self.id))
            if existing_order_ref:
                context["existing_order_ref"] = existing_order_ref
        return context

    def serve(self, request, *args, **kwargs):
        # override form mixin serve() so we can pass request to process_form_submission
        context = None
        if request.method == "POST":
            form = self.get_form(
                request.POST, request.FILES, page=self, user=request.user
            )

            if form.is_valid():
                form_submission = self.process_form_submission(form, request)
                return self.render_landing_page(
                    request, form_submission, *args, **kwargs
                )
        else:
            form = self.get_form(page=self, user=request.user)
            context = self.get_context(request)
            if "existing_order_ref" in context:
                submission = OrderFormSubmission.objects.filter(page=self, reference=context["existing_order_ref"]).first()
                # Don't render the form page with any existing order if it's already paid
                if submission and not submission.paid:
                    for field_name, field in form.fields.items():
                        if field_name in submission.form_data:
                            field.initial = submission.form_data[field_name]
                    _, total, discount = self.get_variant_quantities_and_total(submission.form_data)
                    context["existing_order_total"] = total
                    context["existing_order_discount"] = discount
                else:
                    del context["existing_order_ref"]
                    if self.id in request.session.get("orders", {}):
                        del request.session["orders"][str(self.id)]
        context = context or self.get_context(request)
        context["form"] = form
        return TemplateResponse(request, self.get_template(request), context)
        

    def process_form_submission(self, form, request=None):
        """
        Accepts form instance with submitted data, user and page.
        Creates submission instance.

        Set cost here to set the cost at the time of submission (in case prices)
        changed or voucher codes were deactivated
        """
        cleaned_data = form.cleaned_data

        for name, field in form.fields.items():
            if isinstance(field, WagtailImageField):
                image_file_data = cleaned_data[name]
                if image_file_data:
                    ImageModel = get_image_model()
                    kwargs = {
                        'file': cleaned_data[name],
                        'title': self.get_image_title(cleaned_data[name].name),
                        'collection': self.get_uploaded_image_collection(),
                    }

                    if form.user and not form.user.is_anonymous:
                        kwargs['uploaded_by_user'] = form.user

                    image = ImageModel(**kwargs)
                    image.save()
                    # saving the image id
                    # alternatively we can store a path to the image via image.get_rendition
                    cleaned_data.update({name: f"{self.get_uploaded_image_collection().name}/{image.filename}"})
                else:
                    # remove the value from the data
                    del cleaned_data[name]

        # Don't call super to send the email to the to_address, as we want to use
        # the saved submission for email context
        remove_captcha_field(form)

        # Do we have an unpaid submission for this order?
        existing_submission = None
        if request is not None:
            existing_session_order_ref = request.session.get("orders", {}).get(str(self.id))
            if existing_session_order_ref:
                submission = self.get_submission_class().objects.filter(reference=existing_session_order_ref).first()
                if submission:
                    if not submission.paid:
                        existing_submission = submission
                    else:
                        if self.id in request.session.get("orders", {}):
                            del request.session["orders"][str(self.id)]

        if existing_submission:
            submission = existing_submission
            submission.form_data = form.cleaned_data
            submission.save()
        else:
            submission = self.get_submission_class().objects.create(
                form_data=form.cleaned_data,
                page=self,
            )

        _, total, discount = self.get_variant_quantities_and_total(form.cleaned_data)

        subject = self.subject
        if existing_submission:
            subject = f"{self.subject} (UPDATED)"

        if self.to_address:
            self.send_mail(form, submission, total, discount, subject)
        
        submission.cost = total
        submission.save()

        # Send email to purchaser
        send_mail(
            subject,
            self.render_email_for_purchaser(submission, total, discount),
            [submission.email],
            settings.DEFAULT_FROM_EMAIL,
            reply_to=[settings.DEFAULT_ADMIN_EMAIL],
        )

        # Add ref to session if processing with a request
        if request is not None:
            request.session["orders"] = {str(self.id): submission.reference}

        return submission
    

class OrderFormSubmission(AbstractFormSubmission):
    reference = ShortUUIDField(
        editable = False
    )
    form_data = EncryptedJSONField(encoder=DjangoJSONEncoder)
    paid = models.BooleanField(default=False)
    date_paid = models.DateTimeField(null=True, blank=True)
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
        variant_quantities, _, _ = self.page.specific.get_variant_quantities_and_total(self.form_data)
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
    
    def save(self, *args, **kwargs):
        if self.paid and not self.date_paid:
            self.date_paid = timezone.now()
            # This submission has just been marked as paid; look for a one-time voucher
            # used for it, and deactivate it if applicable
            # We don't do this for subsequent saves, because the code could have been
            # reactivated for another use
            voucher_code = self.form_data.get("voucher_code")
            if voucher_code:
                # is there a matching one-time use voucher? If so, deactivate it now
                try:
                    voucher = OrderVoucher.objects.get(code=voucher_code, one_time_use=True)
                    voucher.active = False
                    voucher.save()
                except OrderVoucher.DoesNotExist:
                    ...
        super().save(*args, **kwargs)
    

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

    parent_page_types = ["HomePage"]
    subpage_types = ["OrderFormPage"]


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


class NewsPage(Page):
    parent_page_types = ["HomePage"]
    subpage_types = ["NewsItemPage"]
    paginate_by = 10
    body = RichTextField(verbose_name="Page body", blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("body")
    ]

    # Returns a queryset of NewsItemPage objects that are live, that are direct
    # descendants of this index page with most recent first
    def get_news_items(self):
        return (
            NewsItemPage.objects.live().descendant_of(self).order_by("-date", "-id")
        )

    # Pagination for the index page. We use the `django.core.paginator` as any
    # standard Django app would, but the difference here being we have it as a
    # method on the model rather than within a view function
    def paginate(self, request):
        page = request.GET.get("page")
        paginator = Paginator(self.get_news_items(), self.paginate_by)
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

        # NewsItemPages objects (get_news_items) are passed through pagination
        news_items = self.paginate(request)

        context["news_items"] = news_items

        return context


class NewsItemPage(Page):
    parent_page_types = ["NewsPage"]
    subpage_types = []

    date = models.DateField(default=datetime.datetime.today)
    body = RichTextField(verbose_name="body")
    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    content_panels = Page.content_panels + [
        FieldPanel("date"),
        FieldPanel("image"),
        FieldPanel("body")
    ]


class AdventCalendarDay(Orderable):
    """
    Related images for DogPage; hidden on admin
    """
    page = ParentalKey("AdventCalendarPage", on_delete=models.CASCADE, related_name='days')
    image = models.ForeignKey(
        'wagtailimages.Image', on_delete=models.CASCADE, related_name='+'
    )
    caption = models.CharField(max_length=255, null=True, blank=True)

    panels = [
        FieldPanel('image'),
        FieldPanel('caption'),
    ]


class AdventCalendarPage(Page):
    body = RichTextField(verbose_name="body")

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        InlinePanel("days"),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["today_day"] = datetime.datetime.today().day
        return context