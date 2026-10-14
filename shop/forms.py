from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Field, Hidden, Layout, Submit
from django import forms
from django.urls import reverse

from .payment import PAYMENT_METHOD_BUTTON_TEXT


class CheckoutForm(forms.Form):
    email = forms.EmailField()
    email1 = forms.EmailField(label="Email (again)")
    name = forms.CharField(label="Name")
    payment_method = forms.CharField()
    shipping_method = forms.CharField()
    shipping_address = forms.CharField(
        widget=forms.Textarea(attrs={"cols": 40, "rows": 6}),
    )
    billing_address = forms.CharField()

    def __init__(self, **kwargs):
        payment_method = kwargs.pop("payment_method")
        shipping_method = kwargs.pop("shipping_method")
        super().__init__(**kwargs)
        self.helper = FormHelper()
        self.fields["payment_method"].initial = payment_method
        self.fields["shipping_method"].initial = shipping_method

        # shipping_address and billing_address are required fields for the
        # checkout serializer (but can be blank)
        # We currently never need to collect billing address as it will be
        # handled by Stripe
        if shipping_method != "collect":
            shipping_address_layout = "shipping_address"
        else:
            shipping_address_layout = Hidden("shipping_address", "-")

        self.helper.layout = Layout(
            Hidden("payment_method", payment_method),
            Hidden("shipping_method", shipping_method),
            Hidden("billing_address", "-"),
            "name",
            "email",
            "email1",
            shipping_address_layout,
            Submit("submit", PAYMENT_METHOD_BUTTON_TEXT[payment_method]),
        )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        email1 = cleaned_data.get("email1")
        if email != email1:
            self.add_error("email1", "Email fields do not match")
        return cleaned_data
