import wagtail_factories

from ..models import FormPage, OrderFormPage


class FormPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = FormPage


class OrderFormPageFactory(wagtail_factories.PageFactory):
    title = "Test Order Form"
    to_address = "admin@test.com"
    subject = "test order"
    class Meta:
        model = OrderFormPage
