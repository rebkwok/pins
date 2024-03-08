# -*- coding: utf-8 -*-
from model_bakery import baker
from urllib.parse import urlencode
from unittest.mock import patch

import pytest

from django.conf import settings
from django.core import mail
from django.urls import reverse


from fundraising.models import RecipeBookSubmission
from paypal.standard.ipn.models import PayPalIPN

pytestmark = pytest.mark.django_db


def test_paypal_return_recipe_submission(client):
    submission = baker.make(RecipeBookSubmission, page_type="single")
    session = client.session
    session["paypal_item_reference"] = submission.reference
    session.save()

    url = reverse("payments:paypal_return")
    resp = client.get(url)
    assert resp.context["item"] == submission
    assert resp.context["item_type"] == "submission"


def test_paypal_return_order_form(client, order_form_submission):
    submission = order_form_submission()
    session = client.session
    session["paypal_item_reference"] = submission.reference
    session.save()

    url = reverse("payments:paypal_return")
    resp = client.get(url)
    assert resp.context["item"] == submission
    assert resp.context["item_type"] == "order"


def test_paypal_return_no_reference(client):
    url = reverse("payments:paypal_return")
    resp = client.get(url)
    assert resp.status_code == 200
    assert "item" not in resp.context
    assert "item_type" not in resp.context
    assert "We will send you an email when your payment has been processed." in resp.content.decode()
