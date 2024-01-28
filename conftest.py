from unittest.mock import patch

from model_bakery import baker
from wagtail.models import Site

import pytest

import wagtail_factories

from home.tests.conftest import FormPageFactory, OrderFormPageFactory
from home.models import FormField, OrderFormField, ProductVariant, OrderFormSubmission


pytestmark = pytest.mark.django_db


class HomePageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = "home.HomePage"


@pytest.fixture(autouse=True)
def root_page():
    page = wagtail_factories.PageFactory(parent=None)
    Site.objects.create(
        hostname='localhost',
        port=8000,
        root_page=page
    )
    yield page


@pytest.fixture
def home_page(root_page):
    yield HomePageFactory(
        parent=root_page, title="Home", hero_text="Home", hero_cta="Test", body="Test"
    )


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
    form_page = OrderFormPageFactory(
        parent=home_page, title="Test Order Form", to_address="admin@test.com", subject="test order",
    )
    baker.make(OrderFormField, label="name", field_type="singleline", page=form_page)
    baker.make(OrderFormField, label="email_address", field_type="email", page=form_page)
    
    # Make an order form field matching a product variant.
    baker.make(OrderFormField, label="pv__test_product", field_type="dropdown", page=form_page, default_value=1)
    baker.make(ProductVariant, page=form_page, name="test product", cost=10, item_count=1)
    form_page.save()
    yield form_page


@pytest.fixture
def order_form_submission(order_form_page):
    def _submission(form_data=None):
        form_data = form_data or {}
        form_class = order_form_page.get_form_class()
        form = form_class(
            {
                "name": "Mickey Mouse",
                "email_address": "mickey.mouse@test.com",
                "pv__test_product": 2,
                "g-recaptcha-response": "PASSED",
                **form_data
            },
            page=order_form_page
        )
        assert form.is_valid()
        submission = order_form_page.process_form_submission(form)
        return submission
    return _submission


@pytest.fixture
def order_form_pre_submission(order_form_page):
    def _submission(form_data=None):
        data = {
            "name": "Mickey Mouse",
            "email_address": "mickey.mouse@test.com",
            "pv__test_product": 2,
            **form_data
        }
        return baker.make(
            OrderFormSubmission, page=order_form_page, form_data=data
        )
    return _submission
