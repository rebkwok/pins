from typing import Any
from django import http
from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render, redirect, HttpResponse
from django.template.context_processors import csrf
from django.views.generic import CreateView, DetailView, UpdateView

from crispy_forms.utils import render_crispy_form

from .forms import RecipeBookContrbutionForm, RecipeBookContrbutionEditForm
from .models import RecipeBookSubmission


class RecipeBookSubmissionCreateView(CreateView):

    model = RecipeBookSubmission
    template_name = "fundraising/recipe_book_contribution_add_edit.html"
    form_class = RecipeBookContrbutionForm

    def form_valid(self, form):
        # submit form, create unpaid submission
        # go to detail page with paypal button
        submission = form.save()
        self.send_submission_email(submission)
        return redirect(submission)

    def send_submission_email(self, submission):
        send_mail(
            "Recipe book contribution received!",
            (
                "Thank you for your contribution\n"
                f"You can view your submission at https://{self.request.get_host()}{submission.get_absolute_url()}.\n"
                f"If you have not already made your payment, you can find a PayPal link there too.\n"
                "Thank you for supporting Podencos In Need (PINS) <3."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [submission.email],
            fail_silently=False,
        )
        send_mail(
            "A new recipe book contribution has been received",
            (
                f"From: {submission.name}\n"
                f"Page type: {submission.page_type_verbose()}\n"
            ),
            settings.DEFAULT_FROM_EMAIL,
            [settings.CC_EMAIL],
            fail_silently=False,
        )
    

class RecipeBookSubmissionDetailView(DetailView):

    model = RecipeBookSubmission
    template_name = "fundraising/recipe_book_contribution_detail.html"
    context_object_name = "submission"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        # Add in paypal form if unpaid
        return context


class RecipeBookSubmissionUpdateView(UpdateView):

    model = RecipeBookSubmission
    template_name = "fundraising/recipe_book_contribution_add_edit.html"
    context_object_name = "submission"
    form_class = RecipeBookContrbutionEditForm

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.processing or obj.complete:
            return redirect(obj)
        return super().dispatch(request, *args, **kwargs)

def update_form_fields(request):
    ctx = {}
    ctx.update(csrf(request))
    initial = {k: request.POST.get(k) for k in request.POST }
    form = RecipeBookContrbutionForm(initial=initial, page_type=request.POST.get("page_type"))
    return HttpResponse(render_crispy_form(form, context=ctx))