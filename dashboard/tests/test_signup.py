from unittest.mock import patch

import pytest
from django.urls import reverse

from django_recaptcha.client import RecaptchaResponse


@pytest.fixture
def signup_data():
    return {
        "email": "mickey.mouse@test.com",
        "username": "mickeymouse",
        "first_name": "Mickey",
        "last_name": "Mouse",
        "password1": "a-Str0ng-passw0rd!",
        "password2": "a-Str0ng-passw0rd!",
        "data_processing_consent": True,
        "g-recaptcha-response": "PASSED",
    }


@pytest.mark.django_db
def test_signup_page_renders_captcha(client):
    resp = client.get(reverse("account_signup"))
    assert resp.status_code == 200
    assert "g-recaptcha" in resp.content.decode()


@pytest.mark.django_db
@patch("django_recaptcha.fields.client.submit")
def test_signup_with_valid_captcha(mock_submit, client, django_user_model, signup_data):
    mock_submit.return_value = RecaptchaResponse(is_valid=True)
    resp = client.post(reverse("account_signup"), signup_data)
    assert resp.status_code == 302, resp.context["form"].errors
    assert django_user_model.objects.filter(email="mickey.mouse@test.com").exists()


@pytest.mark.django_db
@patch("django_recaptcha.fields.client.submit")
def test_signup_with_invalid_captcha(mock_submit, client, django_user_model, signup_data):
    mock_submit.return_value = RecaptchaResponse(is_valid=False, extra_data={"error-codes": ["invalid"]})
    resp = client.post(reverse("account_signup"), signup_data)
    assert resp.status_code == 200
    assert "captcha" in resp.context["form"].errors
    assert not django_user_model.objects.filter(email="mickey.mouse@test.com").exists()
