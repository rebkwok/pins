from unittest.mock import patch

from model_bakery import baker

import pytest

import wagtail_factories

from ..models import FormPage, FormField, OrderFormPage, OrderFormField, ProductVariant, OrderFormSubmission

pytestmark = pytest.mark.django_db


class FormPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = FormPage


class OrderFormPageFactory(wagtail_factories.PageFactory):
    shipping_cost = 2
    class Meta:
        model = OrderFormPage


@pytest.fixture
def contact_form_page(home_page):
    form_page = FormPageFactory(
        parent=home_page, title="Test Contact Form", to_address="admin@test.com", subject="contact"
    )
    baker.make(FormField, label="subject", field_type="singleline", page=form_page)
    baker.make(FormField, label="email_address", field_type="email", page=form_page)
    baker.make(FormField, label="message", field_type="multiline", page=form_page)
    yield form_page


@pytest.fixture
def order_form_page(home_page):
    with patch("home.models.OrderFormPage.clean"):
        form_page = OrderFormPageFactory(
            parent=home_page, title="Test Order Form", to_address="admin@test.com", subject="test order",
        )
    baker.make(OrderFormField, label="name", field_type="singleline", page=form_page)
    baker.make(OrderFormField, label="email_address", field_type="email", page=form_page)
    
    # Make an order form field matching a product variant.
    baker.make(OrderFormField, label="pv__test_product", field_type="dropdown", page=form_page, default_value=1)
    baker.make(ProductVariant, page=form_page, name="test product", cost=10)
    form_page.save()
    yield form_page


@pytest.fixture
def order_form_submission(order_form_page):
    def _submission(form_data):
        data = {
            "name": "Mickey Mouse",
            "email": "mickey.mouse@test.com",
            "pv__test_product": 2,
            **form_data
        }
        return baker.make(
            OrderFormSubmission, page=order_form_page,
            form_data=data    
        )
    return _submission