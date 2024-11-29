from django import forms
from django.utils.safestring import mark_safe


def data_processing_consent_field():
    return forms.BooleanField(
        required=True,
            label="Data processing consent",
            help_text=mark_safe(
                "Our <a href='/privacy-policy/'>Data Privacy Policy</a> explains how we may collect and process your personal information. "
                "Please confirm that you have read and consent to this."
            )
    )
