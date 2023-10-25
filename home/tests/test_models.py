import datetime

from django.core import mail
from django.test import RequestFactory

from model_bakery import baker

import pytest

import wagtail_factories

from ..models import FormPage, FormField, FooterText

pytestmark = pytest.mark.django_db


class FormPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = FormPage


@pytest.fixture
def contact_form_page(home_page):
    form_page = FormPageFactory(
        parent=home_page, title="Test Contact Form", to_address="admin@test.com", subject="contact"
    )
    baker.make(FormField, label="subject", field_type="singleline", page=form_page)
    baker.make(FormField, label="email_address", field_type="email", page=form_page)
    baker.make(FormField, label="message", field_type="multiline", page=form_page)
    yield form_page


def test_home_page_str(home_page):
    assert str(home_page) == "Home"


def test_form_page(contact_form_page, client):
    request = RequestFactory().get(contact_form_page.url)
    request.user = None
    resp = contact_form_page.serve(request)
    assert list(resp.context_data["form"].fields.keys()) == ["subject", "email_address", "message"]


def test_form_page_with_ref(contact_form_page):
    request = RequestFactory().get(contact_form_page.url + "?ref=doug")
    request.user = None
    resp = contact_form_page.serve(request)
    assert resp.context_data["form"].fields["subject"].initial == "Enquiry about doug"

def test_form_page_send_email(contact_form_page):
    # if a form has an email_address and subject field, they replace the reply-to and
    # subject in the email
    assert len(mail.outbox) == 0
    
    form_class = contact_form_page.get_form_class()
    form = form_class(
        {"subject": "enquiry", "email_address": "test@test.com", "message": "A message"}
    )
    assert form.is_valid()
    contact_form_page.send_mail(form)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["admin@test.com"]
    assert mail.outbox[0].subject == "enquiry"
    assert mail.outbox[0].reply_to == ["test@test.com"]
    assert mail.outbox[0].body == "From: test@test.com\n\nmessage:\nA message"


def test_form_page_send_email_other_fields(home_page):
    assert len(mail.outbox) == 0
    form_page = FormPageFactory(
        parent=home_page, title="Test Form", to_address="admin@test.com", subject="test"
    )
    baker.make(FormField, label="date", field_type="date", page=form_page)
    baker.make(FormField, label="datetime", field_type="datetime", page=form_page)
    baker.make(
        FormField, label="list", field_type="multiselect", 
        choices="a,b,c", 
        page=form_page
    )

    form_class = form_page.get_form_class()
    form = form_class(
        {"date": datetime.date(2023, 12, 15), "datetime": datetime.datetime(2023, 8, 1, 12, 0), "list": ["a", "b"]}
    )
    assert form.is_valid()
    
    form_page.send_mail(form)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["admin@test.com"]
    assert mail.outbox[0].subject == "test"
    assert mail.outbox[0].reply_to == [None]
    assert mail.outbox[0].body == "date: 15-Dec-2023\n\ndatetime: 01-Aug-2023 12:00\n\nlist: a, b"


def test_footer_text(home_page):
    footer = FooterText.objects.create(body="I am a footer")
    assert str(footer) == "Footer text"
    request = RequestFactory().get(home_page.url)
    resp = home_page.serve(request)
    assert "I am a footer" in resp.rendered_content

    assert footer.get_preview_context(request, None) == {"footer_text": "I am a footer"}
    assert footer.get_preview_template(request, None) == "base.html"
