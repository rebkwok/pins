from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Field, Hidden, Layout, Submit
from django import forms
from django.urls import reverse

from .payment import PAYMENT_METHOD_BUTTON_TEXT


class CheckoutForm(forms.Form):
    email = forms.EmailField()
    email1 = forms.EmailField(label="Email (again)")
    payment_method = forms.CharField()
    shipping_address = forms.CharField(
        widget=forms.Textarea(attrs={"cols": 40, "rows": 6})
    )
    billing_address = forms.CharField(
        widget=forms.Textarea(attrs={"cols": 40, "rows": 6})
    )

    def __init__(self, **kwargs):
        payment_method = kwargs.pop("payment_method")
        super().__init__(**kwargs)
        self.helper = FormHelper()
        self.fields["payment_method"].initial = payment_method

        self.helper.layout = Layout(
            Hidden("payment_method", payment_method),
            "email",
            "email1",
            "shipping_address",
            Button(
                "copy_shipping_address",
                "Copy shipping address for billing",
                css_class="btn btn-outline-primary",
                **{
                    "hx-target": ".billing_address_wrapper",
                    "hx-get": reverse("shop:copy_shipping_address"),
                    "hx-include": "[id='id_shipping_address']",
                }
            ),
            Field(
                "billing_address",
                wrapper_class="billing_address_wrapper",
            ),
            Submit("submit", PAYMENT_METHOD_BUTTON_TEXT[payment_method]),
        )
