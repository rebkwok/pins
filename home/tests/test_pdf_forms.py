from datetime import timedelta

import pytest

from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.auth.models import AnonymousUser, User
from django.core import mail
from django.utils import timezone

from model_bakery import baker

from .conftest import PDFFormPageFactory

pytestmark = pytest.mark.django_db


def test_pdf_form_submission(pdf_form_submission):
    submission = pdf_form_submission()
    assert submission.is_draft
    assert submission.token is not None
    assert submission.token_active(submission.token)
    assert submission.status == "Draft"
    assert submission.name == "Mickey Mouse"
    assert submission.email == "mickey.mouse@test.com"
    assert submission.display_data() == {
        "A field": "Foo\nbar",
        "A multicheckbox": "yes, no",
        "A checkbox": "Yes",
    }
    assert (
        submission.get_download_filename() == 
        f"test-application-form-Mickey-Mouse-{submission.reference}.pdf"
    )

    submission.is_draft = False
    submission.save()
    assert submission.status == "Submitted"

def test_pdf_form_page_builder_no_name_or_email_field(home_page):
    pdfformpage = PDFFormPageFactory(parent=home_page)
    builder =  pdfformpage.form_builder(pdfformpage.pdf_form_fields.all())
    assert list(builder.formfields.keys()) == ["name", "email"]

def test_pdf_form_page_builder_with_email_field(home_page):
    pdfformpage = PDFFormPageFactory(parent=home_page)
    baker.make("home.PDFFormField", label="Email address", field_type="email", page=pdfformpage)
    builder =  pdfformpage.form_builder(pdfformpage.pdf_form_fields.all())
    assert list(builder.formfields.keys()) == ["name", "email_address"]


def test_pdf_form_page_required_fields(home_page):
    pdfformpage = PDFFormPageFactory(parent=home_page)
    email_field = baker.make(
        "home.PDFFormField", 
        label="Email address", 
        field_type="email", 
        page=pdfformpage,
        required=False
    )
    form_field = baker.make(
        "home.PDFFormField", 
        label="Foo", 
        field_type="singleline", 
        page=pdfformpage,
        required=True
    )
    email_field.save()
    form_field.save()
    assert email_field.required
    assert not form_field.required


def test_pdf_form_page_serve_get(pdf_form_page, rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    resp = pdf_form_page.serve(request)
    assert resp.status_code == 200


def test_pdf_form_page_serve_get_with_reference_no_token(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    request = rf.get(f"/?reference={submission.reference}")
    request.user = AnonymousUser()
    resp = pdf_form_page.serve(request)
    assert resp.status_code == 302
    assert resp.url == submission.get_absolute_url()


def test_pdf_form_page_serve_get_with_reference_no_token_staff_user(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    request = rf.get(f"/?reference={submission.reference}")
    request.user = baker.make(User, is_staff=True)
    resp = pdf_form_page.serve(request)
    # Staff users also can't see the edit form without a token
    assert resp.status_code == 302


def test_pdf_form_page_serve_get_with_reference_no_token_author_user(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    request = rf.get(f"/?reference={submission.reference}")
    request.user = baker.make(User, email=submission.email)
    resp = pdf_form_page.serve(request)
    assert resp.status_code == 200

def test_pdf_form_page_serve_get_with_reference_and_valid_token(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    request = rf.get(f"/?reference={submission.reference}&token={submission.token}")
    request.user = AnonymousUser()
    resp = pdf_form_page.serve(request)
    assert resp.context_data["form"].instance == submission
    assert resp.context_data["form"].initial == submission.form_data
    assert resp.status_code == 200


def test_pdf_form_page_serve_get_with_submitted_form(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    submission.is_draft = False
    submission.save()
    request = rf.get(f"/?reference={submission.reference}&token={submission.token}")
    request.user = AnonymousUser()
    resp = pdf_form_page.serve(request)
    assert resp.status_code == 302
    assert resp.url == submission.get_absolute_url_with_token()


def test_pdf_form_page_serve_get_with_reference_and_invalid_token(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    request = rf.get(f"/?reference={submission.reference}&token=foo")
    request.user = AnonymousUser()
    resp = pdf_form_page.serve(request)
    assert resp.status_code == 302
    assert resp.url == submission.get_absolute_url() + "?token=foo"


def test_pdf_form_page_serve_get_with_reference_and_expired_token(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    submission.token_expiry = timezone.now() - timedelta(1)
    submission.save()
    request = rf.get(f"/?reference={submission.reference}&token={submission.token}")
    request.user = AnonymousUser()
    resp = pdf_form_page.serve(request)
    # expired token is allowed for form editing
    assert resp.status_code == 200


def test_pdf_form_page_serve_get_invalid_reference(
        pdf_form_page, pdf_form_submission, rf
    ):
    submission = pdf_form_submission()
    request = rf.get(f"/?reference=foo&token={submission.token}")
    request.user = AnonymousUser()
    resp = pdf_form_page.serve(request)
    # Goes to page but with a new form
    assert resp.status_code == 200
    assert resp.context_data["form"].instance is None
    assert resp.context_data["form"].initial == {}


def setup_request(request, user=None):
    request.user = user or AnonymousUser()
    sm = SessionMiddleware(lambda x: x)
    sm.process_request(request)
    mm = MessageMiddleware(lambda x: x)
    mm.process_request(request)


def test_pdf_form_page_serve_post_save_draft(pdf_form_page, rf):
    assert not pdf_form_page.pdfformsubmission_set.exists()
    # partial data
    data = {
        "name": "Mickey Mouse",
        "email": "mickey.mouse@test.com",
        "a_field": "Foo\r\nbar",
        "save_as_draft": True
    }
    request = rf.post("/", data)
    setup_request(request)

    pdf_form_page.serve(request)
    assert pdf_form_page.pdfformsubmission_set.count() == 1
    assert pdf_form_page.pdfformsubmission_set.first().status == "Draft"


def test_pdf_form_page_serve_post_save_draft(pdf_form_page, rf):
    assert not pdf_form_page.pdfformsubmission_set.exists()
    # partial data
    data = {
        "name": "Mickey Mouse",
        "email": "mickey.mouse@test.com",
        "a_field": "Foo\r\nbar",
        "save_as_draft": True
    }
    request = rf.post("/", data)
    setup_request(request)

    pdf_form_page.serve(request)
    assert pdf_form_page.pdfformsubmission_set.count() == 1
    submission = pdf_form_page.pdfformsubmission_set.first()
    assert submission.status == "Draft"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["mickey.mouse@test.com"]

    # Saving as draft again doesn't re-send email
    data["reference"] = submission.reference
    request = rf.post(f"/", data)
    setup_request(request)
    pdf_form_page.serve(request)
    assert pdf_form_page.pdfformsubmission_set.count() == 1
    assert len(mail.outbox) == 1


def test_pdf_form_page_serve_post_submit_missing_form_data(pdf_form_page, rf):
    assert not pdf_form_page.pdfformsubmission_set.exists()
    # partial data
    data = {
        "name": "Mickey Mouse",
        "email": "mickey.mouse@test.com",
        "a_field": "Foo\r\nbar",
        "submit": "Submit"
    }
    request = rf.post("/", data)
    setup_request(request)

    resp = pdf_form_page.serve(request)
    assert resp.status_code == 200
    assert resp.context_data["form"].errors == {
        'a_checkbox': ['This field is required'],
        'a_multicheckbox': ['This field is required']
    }


def test_pdf_form_page_serve_post_submit(pdf_form_page, rf):
    assert not pdf_form_page.pdfformsubmission_set.exists()
    # partial data
    data = {
        "name": "Mickey Mouse",
        "email": "mickey.mouse@test.com",
        "a_checkbox": True,
        "a_multicheckbox": ["yes"],
        "a_field": "Foo\r\nbar",
        "submit": "Submit"
    }
    request = rf.post("/", data)
    setup_request(request)

    pdf_form_page.serve(request)
    assert pdf_form_page.pdfformsubmission_set.count() == 1
    submission = pdf_form_page.pdfformsubmission_set.first()
    assert submission.status == "Submitted"
    assert len(mail.outbox) == 2
    assert mail.outbox[0].to == ["admin@test.com"]
    assert mail.outbox[1].to == ["mickey.mouse@test.com"]
