from django import forms

from allauth.account.forms import SignupForm

from common.fields import data_processing_consent_field


class PINSSignupForm(SignupForm):

    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)
    data_processing_consent = data_processing_consent_field()
