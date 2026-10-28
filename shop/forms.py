import re

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Div, Fieldset, Hidden, Layout, Submit
from django import forms
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import SHIPPING_COLLECT, SHIPPING_DELIVER, UK
from .payment import PAYMENT_METHOD_BUTTON_TEXT



class MainButton(Submit):
    """The page's main action, in the shop's button style (not Bootstrap blue)"""

    field_classes = "btn basket-btn shop-main-btn"

# Where the shop's policies are (pages on the site)
PRIVACY_POLICY_URL = "/privacy-policy/"
CONTACT_URL = "/contact-us/"

UK_ONLY_NOTE = mark_safe(
    "Please note this order form is for shipping within the UK ONLY. If you are "
    f'ordering from outside the UK, please <a href="{CONTACT_URL}">contact us</a> for '
    "shipping costs before placing an order."
)

COUNTRY_OTHER = "other"
COUNTRY_CHOICES = [(UK, UK), (COUNTRY_OTHER, "Other")]

# A UK postcode (loosely: outward code, then inward code), e.g. SW1A 1AA
UK_POSTCODE = re.compile(r"^([A-Z]{1,2}[0-9][A-Z0-9]?) ?([0-9][A-Z]{2})$")


def tidy_uk_postcode(postcode):
    """e.g. "sw1a1aa" -> "SW1A 1AA"; None if it isn't a UK postcode"""
    match = UK_POSTCODE.match(" ".join(postcode.upper().split()))
    return f"{match[1]} {match[2]}" if match else None


class CheckoutForm(forms.Form):
    email = forms.EmailField()
    email1 = forms.EmailField(label="Email (again)")
    name = forms.CharField(label="Name")
    phone = forms.CharField(
        label="Mobile number",
        required=False,
        max_length=40,
        # (help text by shipping method, see __init__)
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
    )
    payment_method = forms.CharField()
    shipping_method = forms.CharField()
    # (the formatted address, from the address fields, for salesman's checkout)
    shipping_address = forms.CharField(required=False)
    billing_address = forms.CharField()

    # The delivery address
    address_line1 = forms.CharField(
        label="Address line 1", max_length=255,
        widget=forms.TextInput(attrs={"autocomplete": "address-line1"}),
    )
    address_line2 = forms.CharField(
        label="Address line 2", max_length=255, required=False,
        widget=forms.TextInput(attrs={"autocomplete": "address-line2"}),
    )
    town = forms.CharField(
        label="Town or city", max_length=255,
        widget=forms.TextInput(attrs={"autocomplete": "address-level2"}),
    )
    county = forms.CharField(label="County", max_length=255, required=False)
    # (UK postcodes are checked, see clean; outside the UK, anything, e.g. a
    # zip code, or N/A)
    postcode = forms.CharField(
        label="Postcode", max_length=20,
        widget=forms.TextInput(attrs={"autocomplete": "postal-code"}),
    )
    country = forms.ChoiceField(label="Country", choices=COUNTRY_CHOICES, initial=UK)
    other_country = forms.CharField(
        label="Which country?", max_length=100, required=False,
        help_text=UK_ONLY_NOTE,
    )
    safe_place = forms.CharField(
        label="Safe place",
        max_length=255,
        required=False,
        help_text="Optional: where the parcel can be left if you're out, e.g. in the porch.",
    )

    consent = forms.BooleanField(
        label=mark_safe(
            f'Our <a href="{PRIVACY_POLICY_URL}" target="_blank" rel="noopener">Data '
            "Privacy Policy</a> explains how we may collect and process your personal "
            "information. Please confirm that you have read and consent to this."
        ),
        error_messages={"required": "Please confirm that you consent to this."},
    )

    ADDRESS_FIELDS = (
        "address_line1", "address_line2", "town", "county", "postcode", "country",
        "other_country", "safe_place",
    )

    def __init__(self, **kwargs):
        payment_method = kwargs.pop("payment_method")
        shipping_method = kwargs.pop("shipping_method")
        # Nothing to pay (a discount code covers the whole basket)
        free = kwargs.pop("free", False)
        super().__init__(**kwargs)
        self.helper = FormHelper()
        self.fields["payment_method"].initial = payment_method
        self.fields["shipping_method"].initial = shipping_method

        # billing_address is a required field for the checkout serializer (but
        # can be blank): we never need it, as Stripe handles it. The shipping
        # address is only needed for delivery (not collection, or orders that
        # don't need shipping).
        self.delivery = shipping_method == SHIPPING_DELIVER
        self.fields["phone"].help_text = {
            SHIPPING_DELIVER: "Optional: for the courier.",
            SHIPPING_COLLECT: "Optional: to arrange collection.",
        }.get(shipping_method, "Optional.")
        if self.delivery:
            address_layout = [
                Fieldset(
                    "Delivery address",
                    HTML(f'<p class="basket-options__help shop-uk-note">{UK_ONLY_NOTE}</p>'),
                    "address_line1",
                    "address_line2",
                    "town",
                    "county",
                    "postcode",
                    "country",
                    Div("other_country", css_class="shop-other-country"),
                    "safe_place",
                ),
            ]
        else:
            for name in self.ADDRESS_FIELDS:
                del self.fields[name]
            address_layout = []

        self.helper.layout = Layout(
            Hidden("payment_method", payment_method),
            Hidden("shipping_method", shipping_method),
            Hidden("billing_address", "-"),
            Fieldset("Your details", "name", "email", "email1", "phone"),
            *address_layout,
            Fieldset("Data processing consent", "consent"),
            MainButton(
                "submit",
                "Place order" if free else PAYMENT_METHOD_BUTTON_TEXT[payment_method],
            ),
        )

    def clean_postcode(self):
        return " ".join(self.cleaned_data["postcode"].split())

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        email1 = cleaned_data.get("email1")
        if email != email1:
            self.add_error("email1", "Email fields do not match")
        if self.delivery:
            if cleaned_data.get("country") == COUNTRY_OTHER:
                if not cleaned_data.get("other_country", "").strip():
                    self.add_error("other_country", "Which country is the address in?")
            elif cleaned_data.get("postcode"):
                postcode = tidy_uk_postcode(cleaned_data["postcode"])
                if postcode is None:
                    self.add_error("postcode", "Enter a UK postcode, e.g. SW1A 1AA.")
                else:
                    cleaned_data["postcode"] = postcode
        return cleaned_data

    @property
    def delivery_country(self):
        """The delivery address's country (UK, or the one given), or "" """
        if not self.delivery:
            return ""
        data = self.cleaned_data
        if data.get("country") == COUNTRY_OTHER:
            return data.get("other_country", "").strip()
        return UK

    def formatted_address(self):
        """The delivery address, one part per line (or "-" without delivery)"""
        if not self.delivery:
            return "-"
        data = self.cleaned_data
        parts = [data.get(name, "").strip() for name in ("address_line1", "address_line2", "town", "county", "postcode")]
        return "\n".join([part for part in parts if part] + [self.delivery_country])

    def checkout_details(self):
        """
        The details to save on the basket (they become the order's, see
        Order.populate_from_basket): name, phone, safe place, country, when
        consent was given, and the address's parts
        """
        data = self.cleaned_data
        details = {
            "name": data["name"],
            "phone": data.get("phone", "").strip(),
            "consent_at": timezone.now().isoformat(),
        }
        if self.delivery:
            details.update(
                safe_place=data.get("safe_place", "").strip(),
                country=self.delivery_country,
                address={
                    name: data.get(name, "").strip()
                    for name in ("address_line1", "address_line2", "town", "county", "postcode")
                },
            )
        return details
