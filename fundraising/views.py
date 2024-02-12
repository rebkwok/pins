from typing import Any
from django import http
from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render, redirect, HttpResponse
from django.urls import reverse
from django.template.response import TemplateResponse
from django.template.context_processors import csrf
from django.views.generic import CreateView, DetailView, UpdateView

from crispy_forms.utils import render_crispy_form
from payments.utils import get_paypal_form


from payments.utils import signature

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

    def form_invalid(self, form):
        form = RecipeBookContrbutionForm(
            data=self.request.POST, files=self.request.FILES, page_type=self.request.POST.get("page_type")
        )
        return super().form_invalid(form)
    
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["new"] = True
        return context
    
    def send_submission_email(self, submission):
        title = f"Recipe title: {submission.title}\n" if submission.page_type != "photo" else ""
        send_mail(
            "Recipe book contribution received!",
            (
                f"Thank you for your contribution!\n{title}\n"
                f"You can view/edit your submission at https://{self.request.get_host()}{submission.get_absolute_url()}.\n"
                f"To edit your submission details you will need your passcode: {submission.code}\n\n"
                "If you have not already made your payment, you can find a PayPal link there too.\n\n"
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
                f"{title}"
            ),
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_ADMIN_EMAIL],
            fail_silently=False,
        )
    

class RecipeBookSubmissionDetailView(DetailView):

    model = RecipeBookSubmission
    template_name = "fundraising/recipe_book_contribution_detail.html"
    context_object_name = "submission"
    
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        submission = context["submission"]
        
        if not submission.paid:
            context["paypal_form"] = get_paypal_form(
                request=self.request,
                amount=submission.cost, 
                item_name=f"Recipe Book submission: {submission.page_type_verbose()}",
                reference=submission.reference
            )
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

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["new"] = False
        return context


def update_form_fields(request):
    ctx = {}
    ctx.update(csrf(request))
    initial = {k: request.POST.get(k) for k in request.POST if k not in ["profile_image", "photo"]}
    form = RecipeBookContrbutionForm(initial=initial, page_type=request.POST.get("page_type"))
    return HttpResponse(render_crispy_form(form, context=ctx))


def char_count(request, fieldname):
    fieldcount = len(request.GET.get(fieldname))
    max_count = int(request.GET.get("max"))
    count_str = f"Character count: {str(fieldcount)}"
    if fieldcount >= max_count:
        count_str = f"<strong class='text-danger'>{count_str}</strong>"
    return HttpResponse(count_str)


def method_char_count(request):
    return char_count(request, "method")


def profile_caption_char_count(request):
    return char_count(request, "profile_caption")


def submitted_recipes(request):
    dog_recipes = RecipeBookSubmission.objects.filter(category="dog").order_by("title").values_list("title", flat=True)
    human_recipes = RecipeBookSubmission.objects.filter(category="human").order_by("title").values_list("title", flat=True)
    return TemplateResponse(
        request, 
        "fundraising/recipe_list.html", 
        {"dog_recipes": dog_recipes, "human_recipes": human_recipes}
    )
