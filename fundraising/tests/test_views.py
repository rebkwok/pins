from pathlib import Path
from unittest.mock import patch


from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.urls import reverse

import pytest

from model_bakery import baker

from ..models import RecipeBookSubmission

pytestmark = pytest.mark.django_db


@pytest.fixture
def image():
    file_path = Path(__file__).parent / "files" / "test.jpg"
    yield SimpleUploadedFile("test.jpg", file_path.read_bytes())


@pytest.fixture
def submission(image):
    with patch("fundraising.models.validate_image_size", return_value=True):
        yield baker.make(RecipeBookSubmission, profile_image=image, photo=image)

def test_create_view_get(client):
    url = reverse("fundraising:recipe_book_contribution_add")
    resp = client.get(url)
    assert resp.status_code == 200
    field_names = [pt.name for pt in resp.context_data["form"].helper.layout.get_field_names()]
    assert field_names == ["name", "email", "email1", "page_type"]
    

def test_create_view_post_profile_image_too_small(client, image):
    assert not RecipeBookSubmission.objects.exists()
    url = reverse("fundraising:recipe_book_contribution_add")
    data = {
        "name": "Test",
        "email": "test@test.com",
        "email1": "test@test.com",
        "page_type": "single",
        "title": "Test", 
        "preparation_time": "10", 
        "cook_time": "10", 
        "servings": "2", 
        "ingredients": "A bean", 
        "method": "Cook the bean",
        "submitted_by": "Me", 
        "profile_image": [image]

    }
    resp = client.post(url, data)
    assert resp.status_code == 200
    form = resp.context_data["form"]
    assert "Size should be at least 710 x 520 pixels" in form.errors["profile_image"][0]
    assert not RecipeBookSubmission.objects.exists()


def test_create_view_post_single_page(client, image):
    assert not RecipeBookSubmission.objects.exists()
    url = reverse("fundraising:recipe_book_contribution_add")
    data = {
        "name": "Test",
        "email": "test@test.com",
        "email1": "test@test.com",
        "page_type": "single",
        "title": "Test", 
        "preparation_time": "10", 
        "cook_time": "10", 
        "servings": "2", 
        "ingredients": "A bean", 
        "method": "Cook the bean",
        "submitted_by": "Me", 
        "profile_image": [image]

    }
    with patch("fundraising.models.validate_image_size", return_value=True):
        resp = client.post(url, data)
    assert resp.status_code == 302
    assert RecipeBookSubmission.objects.exists()
    # sends emails
    assert len(mail.outbox) == 2
    assert mail.outbox[0].to == ["test@test.com"]


def test_create_view_post_email_mismatch(client, image):
    assert not RecipeBookSubmission.objects.exists()
    url = reverse("fundraising:recipe_book_contribution_add")
    data = {
        "name": "Test",
        "email": "test@test.com",
        "email1": "test@test1.com",
        "page_type": "single",
        "title": "Test", 
        "preparation_time": "10", 
        "cook_time": "10", 
        "servings": "2", 
        "ingredients": "A bean", 
        "method": "Cook the bean",
        "submitted_by": "Me", 
        "profile_image": [image]

    }
    with patch("fundraising.models.validate_image_size", return_value=True):
        resp = client.post(url, data)
    assert resp.status_code == 200
    form = resp.context_data["form"]
    assert form.errors == {"email1": ["Email fields do not match"]}


def test_unpaid_submission_detail_view(client, submission):
    assert not submission.paid
    resp = client.get(submission.get_absolute_url())
    assert "paypal_form" in resp.context_data


def test_paid_submission_detail_view(client, submission):
    submission.paid = True
    submission.save()
    resp = client.get(submission.get_absolute_url())
    assert "paypal_form" not in resp.context_data


@pytest.mark.parametrize(
    "processing,complete,can_edit",
    [
        (False, False, True),
        (False, True, False),
        (True, False, False),
    ]
)
def test_submission_detail_editable(client, submission, processing, complete, can_edit):
    submission.processing = processing
    submission.complete = complete
    submission.save()
    resp = client.get(submission.get_absolute_url())
    assert (reverse("fundraising:recipe_book_contribution_edit", args=(submission.pk,)) in resp.rendered_content) == can_edit


def test_edit_submission(client, submission):
    submission.page_type = "single"
    submission.save()
    url = reverse("fundraising:recipe_book_contribution_edit", args=(submission.pk,))
    data = {
        "id": submission.reference,
        "name": submission.name,
        "email":submission.email,
        "email1":submission.email,
        "page_type": "single",
        "title": "Test", 
        "preparation_time": "10", 
        "cook_time": "10", 
        "servings": "2", 
        "ingredients": "A bean", 
        "method": "Cook the bean",
        "submitted_by": "Me", 
        "profile_image": [image],
        "code_check": submission.code
    }
    with patch("fundraising.models.validate_image_size", return_value=True):
        resp = client.post(url, data)
    assert resp.status_code == 302
    submission.refresh_from_db()
    assert submission.title == "Test"


def test_edit_submission_code_check_fail(client, submission):
    submission.page_type = "single"
    submission.save()
    url = reverse("fundraising:recipe_book_contribution_edit", args=(submission.pk,))
    data = {
        "id": submission.reference,
        "name": submission.name,
        "email":submission.email,
        "email1":submission.email,
        "page_type": "single",
        "title": "Test", 
        "preparation_time": "10", 
        "cook_time": "10", 
        "servings": "2", 
        "ingredients": "A bean", 
        "method": "Cook the bean",
        "submitted_by": "Me", 
        "profile_image": [image],
        "code_check": submission.code - 1,
    }
    with patch("fundraising.models.validate_image_size", return_value=True):
        resp = client.post(url, data)
    assert resp.status_code == 200
    assert resp.context_data["form"].errors == {"code_check": ["Code is invalid"]}


@pytest.mark.parametrize(
    "processing,complete,redirects",
    [
        (False, False, False),
        (False, True, True),
        (True, False, True),
    ]
)
def test_edit_submission_processing_complete_redirects(client, submission, processing, complete, redirects):
    submission.processing = processing
    submission.complete = complete
    submission.save()
    url = reverse("fundraising:recipe_book_contribution_edit", args=(submission.pk,))
    resp = client.get(url)
    if redirects:
        assert resp.status_code == 302
        assert resp.url == submission.get_absolute_url()
    else:
        assert resp.status_code == 200


@pytest.mark.parametrize(
    "method_content",
    [
        "h", "hello", "longer than max"
    ]
)
def test_method_char_count(client, method_content):
    url = reverse("fundraising:method_char_count") + f"?max=10&method={method_content}"
    resp = client.get(url)
    assert f"Character count: {len(method_content)}" in resp.content.decode()
    assert ("text-danger" in resp.content.decode()) == (len(method_content) >= 10)


@pytest.mark.parametrize(
    "caption_content",
    [
        "h", "hello", "longer than max"
    ]
)
def test_method_char_count(client, caption_content):
    url = reverse("fundraising:profile_caption_char_count") + f"?max=10&profile_caption={caption_content}"
    resp = client.get(url)
    assert f"Character count: {len(caption_content)}" in resp.content.decode()
    assert ("text-danger" in resp.content.decode()) == (len(caption_content) >= 10)