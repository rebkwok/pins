from datetime import datetime, UTC
from unittest.mock import patch

from model_bakery import baker
from wagtail.models import Site

import pytest

import wagtail_factories

from home.tests.conftest import (
    FormPageFactory, OrderFormPageFactory, PDFFormPageFactory
)
from home.models import (
    FormField, 
    OrderFormField, 
    ProductVariant, 
    OrderFormSubmission, 
    OrderShippingCost,
    PDFFormField,
    PDFFormSubmission,
)

from salesman.core.utils import get_salesman_model

from shop.models import SaleCategory, SaleProduct
from shop.tests.factories import CategoryPageFactory, ShopPageFactory

Basket = get_salesman_model("Basket")


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    # Files saved by tests (e.g. images) go in a temporary directory, not the
    # project's media directory
    settings.MEDIA_ROOT = str(tmp_path / "media")

Order = get_salesman_model("Order")

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
    
    baker.make(OrderShippingCost, amount=2, order_form_page=form_page)

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
                "data_processing_consent": True,
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
            "data_processing_consent": True,
            "pv__test_product": 2,
            **form_data
        }
        return baker.make(
            OrderFormSubmission, page=order_form_page, form_data=data
        )
    return _submission


@pytest.fixture
def pdf_form_page(home_page):
    form_page = PDFFormPageFactory(parent=home_page)
    baker.make(PDFFormField, label="A field", field_type="multiline", page=form_page)
    baker.make(PDFFormField, label="A multicheckbox", field_type="checkboxes", page=form_page, choices="yes,no")
    baker.make(PDFFormField, label="A checkbox", field_type="checkbox", page=form_page)

    yield form_page


@pytest.fixture
def pdf_form_submission(pdf_form_page):
    baker.make(PDFFormField, label="Name", field_type="singleline", page=pdf_form_page)
    baker.make(PDFFormField, label="Email", field_type="email", page=pdf_form_page)
    
    def _submission(form_data=None):
        form_data = form_data or {}
        form_class = pdf_form_page.get_form_class()
        form = form_class(
            {
                "name": "Mickey Mouse",
                "email": "mickey.mouse@test.com",
                "data_processing_consent": True,
                "a_field": "Foo\r\nbar",
                "a_multicheckbox": ["yes", "no"],
                "a_checkbox": True,
                **form_data
            },
            page=pdf_form_page
        )
        assert form.is_valid()
        submission, _form = pdf_form_page.process_form_submission(form)
        return submission
    return _submission


@pytest.fixture
def pdf_form_pre_submission(pdf_form_page):
    def _submission(form_data=None):
        data = {
            "name": "Mickey Mouse",
            "email": "mickey.mouse@test.com",
            **form_data
        }
        return baker.make(
            PDFFormSubmission, page=pdf_form_page, form_data=data
        )
    return _submission


@pytest.fixture
def shop_page(home_page):
    yield ShopPageFactory(parent=home_page)


@pytest.fixture
def category_page(shop_page):
    yield CategoryPageFactory(parent=shop_page, title="Test Category")


@pytest.fixture
def product(category_page):
    yield baker.make(
        "shop.Product", name="Test Product", category_page=category_page, price=12
    )


@pytest.fixture
def basket(product):
    basket = baker.make(
        "shop.Basket", extra={"name": "Test User"}, shipping_method="collect"
    )
    variant = baker.make(
        "shop.ProductVariant",
        product=product,
        variant_name="Small",
        price=10,
        stock=5,
    )
    basket.add(variant, quantity=2)
    basket.update(request=None)
    yield basket


@pytest.fixture
def order(basket):
    yield Order.objects.create_from_basket(basket, request=None)


@pytest.fixture
def sale_with_items(product):
    sale = baker.make(
        "shop.Sale",
        name="Test Sale",
        start_date=datetime(2022, 1, 1, tzinfo=UTC),
        end_date=datetime(2022, 1, 2, tzinfo=UTC),
    )
    SaleCategory.objects.create(category=product.category_page, discount=10, sale=sale)
    SaleProduct.objects.create(product=product, discount=20, sale=sale)
    yield sale
