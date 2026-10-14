import pytest

from ..forms import CheckoutForm


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("shipping_method", ["collect", "deliver"])
def test_checkout_form(shipping_method):
    form = CheckoutForm(payment_method="stripe", shipping_method=shipping_method)
    # payment and shipping methods are passed from shopping basked
    assert form.fields["payment_method"].initial == "stripe"
    assert form.fields["shipping_method"].initial == shipping_method


def test_checkout_form_email_fields():
    data = {
        "email": "test@test.com",
        "email1": "tst@test.com",
        "name": "Test",
        "payment_method": "stripe",
        "shipping_method": "collect",
        "billing_address": "-",
        "shipping_address": "-",
    }
    form = CheckoutForm(payment_method="stripe", shipping_method="collect", data=data)
    # payment and shipping methods are passed from shopping basked
    assert not form.is_valid()
    assert form.errors == {"email1": ["Email fields do not match"]}
