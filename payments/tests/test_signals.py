# -*- coding: utf-8 -*-
from datetime import timedelta
from model_bakery import baker
from urllib.parse import urlencode
from unittest.mock import patch

import pytest

from django.conf import settings
from django.core import mail
from django.urls import reverse


from fundraising.models import RecipeBookSubmission
from paypal.standard.ipn.models import PayPalIPN

from ..utils import signature

pytestmark = pytest.mark.django_db


# Parameters are all bytestrings, so we can construct a bytestring
# request the same way that Paypal does.
CHARSET = b"windows-1252"
TEST_RECEIVER_EMAIL = b'dummy-email@hotmail.com'
IPN_POST_PARAMS = {
    "mc_gross": b"7.00",
    "invoice": b"user-PL1-2411152010-inv001",
    "protection_eligibility": b"Ineligible",
    "txn_id": b"51403485VH153354B",
    "last_name": b"User",
    "receiver_email": TEST_RECEIVER_EMAIL,
    "payer_id": b"BN5JZ2V7MLEV4",
    "tax": b"0.00",
    "payment_date": b"23:04:06 Feb 02, 2009 PST",
    "first_name": b"Test",
    "mc_fee": b"0.44",
    "notify_version": b"3.8",
    "custom": b"obj=booking ids=1",
    "payer_status": b"verified",
    "payment_status": b"Completed",
    "business": TEST_RECEIVER_EMAIL,
    "quantity": b"1",
    "verify_sign": b"An5ns1Kso7MWUdW4ErQKJJJ4qi4-AqdZy6dD.sGO3sDhTf1wAbuO2IZ7",
    "payer_email": b"test_user@gmail.com",
    "payment_type": b"instant",
    "payment_fee": b"",
    "receiver_id": b"258DLEHY2BDK6",
    "txn_type": b"web_accept",
    "item_name": b"Recipe Book Contribution",
    "mc_currency": b"GBP",
    "item_number": b"",
    "residence_country": "GB",
    "handling_amount": b"0.00",
    "charset": CHARSET,
    "payment_gross": b"",
    "transaction_subject": b"",
    "ipn_track_id": b"1bd9fe52f058e",
    "shipping": b"0.00",
}


def paypal_post(client, params):
    """
    Does an HTTP POST the way that PayPal does, using the params given.
    Taken from django-paypal
    """
    # We build params into a bytestring ourselves, to avoid some encoding
    # processing that is done by the test client.
    cond_encode = lambda v: v.encode(CHARSET.decode()) if isinstance(v, str) else v
    byte_params = {
        cond_encode(k): cond_encode(v) for k, v in params.items()
    }
    post_data = urlencode(byte_params)
    return client.post(
        reverse('paypal-ipn'),
        post_data, content_type='application/x-www-form-urlencoded'
    )


@patch('paypal.standard.ipn.models.PayPalIPN._postback')
def test_paypal_notify_url_happy_path(mock_postback, client, settings):
    mock_postback.return_value = b"VERIFIED"

    settings.PAYPAL_EMAIL = TEST_RECEIVER_EMAIL.decode()
    submission = baker.make(RecipeBookSubmission, page_type="single")
    assert not PayPalIPN.objects.exists()
    resp = paypal_post(
        client,
        {
            **IPN_POST_PARAMS, 
            'invoice': submission.reference, 
            'custom': signature(submission.reference), 
            'txn_id': 'test',
            'mc_gross': 5,
        }
    )
    assert resp.status_code == 200
    assert PayPalIPN.objects.count() == 1
    ppipn = PayPalIPN.objects.first()
    assert len(mail.outbox) == 1
    assert "Recipe book contribution: payment processed" in mail.outbox[0].subject
    submission.refresh_from_db()
    assert submission.paid
    assert submission.date_paid is not None


@patch('paypal.standard.ipn.models.PayPalIPN._postback')
def test_paypal_notify_url_happy_path_order_submission(mock_postback, client, settings, order_form_submission):
    mock_postback.return_value = b"VERIFIED"

    settings.PAYPAL_EMAIL = TEST_RECEIVER_EMAIL.decode()
    submission = order_form_submission()
    assert not PayPalIPN.objects.exists()
    resp = paypal_post(
        client,
        {
            **IPN_POST_PARAMS, 
            'invoice': submission.reference, 
            'custom': signature(submission.reference), 
            'txn_id': 'test',
            'mc_gross': 22,
        }
    )
    assert resp.status_code == 200
    assert PayPalIPN.objects.count() == 1
    ppipn = PayPalIPN.objects.first()
    # 2 emails on creation of order, 3rd is the payment one
    assert len(mail.outbox) == 3
    assert "Test order: payment processed" in mail.outbox[2].subject
    submission.refresh_from_db()
    assert submission.paid


@patch('paypal.standard.ipn.models.PayPalIPN._postback')
def test_paypal_notify_url_order_submission_with_voucher(
    mock_postback, client, settings, order_form_page, order_form_submission
):
    mock_postback.return_value = b"VERIFIED"
    settings.PAYPAL_EMAIL = TEST_RECEIVER_EMAIL.decode()

    voucher = baker.make(
        "home.OrderVoucher", order_form_page=order_form_page, code="foo", amount=2, 
        active=True, one_time_use=True
    )
    submission = order_form_submission({"voucher_code": "foo"})

    assert not PayPalIPN.objects.exists()
    resp = paypal_post(
        client,
        {
            **IPN_POST_PARAMS, 
            'invoice': submission.reference, 
            'custom': signature(submission.reference), 
            'txn_id': 'test',
            'mc_gross': 20,
        }
    )

    submission.refresh_from_db()
    voucher.refresh_from_db()
    assert submission.paid
    assert not voucher.active


@patch('paypal.standard.ipn.models.PayPalIPN._postback')
def test_paypal_notify_url_unexpected_payment_status(mock_postback, client, settings, caplog):
    mock_postback.return_value = b"VERIFIED"

    settings.PAYPAL_EMAIL = TEST_RECEIVER_EMAIL.decode()
    submission = baker.make(RecipeBookSubmission, page_type="single")
    assert not PayPalIPN.objects.exists()
    paypal_post(
        client,
        {
            **IPN_POST_PARAMS, 
            'invoice': submission.reference, 
            'custom': signature(submission.reference), 
            'txn_id': 'test',
            'mc_gross': 5,
            'payment_status': "Refunded",
        }
    )
    assert PayPalIPN.objects.count() == 1
    assert len(mail.outbox) == 0
    assert "Unexpected status Refunded" in caplog.text
    submission.refresh_from_db()
    assert not submission.paid
    assert submission.date_paid is None


def test_paypal_notify_url_invalid_postback(client, settings, caplog):
    settings.PAYPAL_EMAIL = TEST_RECEIVER_EMAIL.decode()
    submission = baker.make(RecipeBookSubmission, page_type="single")
    assert not PayPalIPN.objects.exists()
    paypal_post(
        client,
        {
            **IPN_POST_PARAMS, 
            'invoice': submission.reference, 
            'custom': signature(submission.reference), 
            'txn_id': 'test',
            'mc_gross': 5,
            'payment_status': "Refunded",
        }
    )
    assert PayPalIPN.objects.count() == 1
    assert len(mail.outbox) == 0
    assert "Invalid postback" in caplog.text
    submission.refresh_from_db()
    assert not submission.paid
    assert submission.date_paid is None


@patch('paypal.standard.ipn.models.PayPalIPN._postback')
def test_paypal_notify_url_complete_with_flag_info(mock_postback, client, settings):
    mock_postback.return_value = b"VERIFIED"

    settings.PAYPAL_EMAIL = TEST_RECEIVER_EMAIL.decode()
    submission = baker.make(RecipeBookSubmission, page_type="single")
    assert not PayPalIPN.objects.exists()
    resp = paypal_post(
        client,
        {
            **IPN_POST_PARAMS, 
            'invoice': submission.reference, 
            'custom': signature(submission.reference), 
            'txn_id': 'test',
            'mc_gross': 5,
            'flag_info': "foo"
        }
    )
    assert resp.status_code == 200
    assert PayPalIPN.objects.count() == 1
    assert len(mail.outbox) == 1
    assert "Recipe book contribution: payment processed" in mail.outbox[0].subject
    submission.refresh_from_db()
    assert submission.paid
    assert submission.date_paid is not None


@pytest.mark.parametrize(
    "post_params,match",
    [
        ({"custom": "foo"}, "Invalid signature"),
        ({"receiver_email": "foo@foo.com"}, "Invalid receiver email"),
        ({"mc_gross": "100"}, "Invalid amount"),
    ]
)
@patch('paypal.standard.ipn.models.PayPalIPN._postback')
def test_paypal_notify_url_errors(mock_postback, client, settings, caplog, post_params, match):
    mock_postback.return_value = b"VERIFIED"

    settings.PAYPAL_EMAIL = TEST_RECEIVER_EMAIL.decode()
    submission = baker.make(RecipeBookSubmission, page_type="single")
    assert not PayPalIPN.objects.exists()
    params = {
        **IPN_POST_PARAMS, 
        'invoice': submission.reference, 
        'custom': signature(submission.reference), 
        'txn_id': 'test',
        'mc_gross': 5,
    }
    params.update(post_params)
    paypal_post(client, params)

    assert PayPalIPN.objects.count() == 1
    assert len(mail.outbox) == 0
    assert match in caplog.text
    submission.refresh_from_db()
    assert not submission.paid
    assert submission.date_paid is None