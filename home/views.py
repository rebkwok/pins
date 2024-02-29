from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, HttpResponse, redirect
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe

from wagtail.admin.mail import send_mail

from .generate_form_submission_pdf import generate_pdf
from .models import OrderFormPage, OrderFormSubmission, PDFFormSubmission
from payments.utils import get_paypal_form


def calculate_order_total_view(request, order_page_id):
    order_page = get_object_or_404(OrderFormPage, pk=order_page_id)
    variant_quantities, total, discount = order_page.get_variant_quantities_and_total(dict(request.POST))
    discount_str = f" (discount £{discount})" if discount else ""
    resp_str = f"<span id='order-total'>{total}{discount_str}</span>"
    
    if request.POST.get("voucher_code", "").strip() and not discount:
        resp_str += f"""
            <div id='invalid-voucher' hx-swap-oob='true' class='text-danger'>
            Voucher code {request.POST.get('voucher_code')} is invalid.
            </div>
        """
    else:
        resp_str += "<div id='invalid-voucher' hx-swap-oob='true'></div>"

    # check quantities are allowed
    allowed, validation_error_msg = order_page.quantity_submitted_is_valid(dict(request.POST))
    
    if not allowed:
        resp_str += f"""
            <div id='not-allowed' hx-swap-oob='true' class='text-danger'>
            {validation_error_msg}
            </div>
        """
    else:
        resp_str += "<div id='not-allowed' hx-swap-oob='true'></div>"
    ordered = "".join(
        [
            f"<li>{variant_quantity[0].group_and_name} ({str(variant_quantity[1])})</li>" 
            for variant_quantity in variant_quantities.values() if variant_quantity[1] > 0
        ]
    )
    resp_str += f"<div id='order-summary' hx-swap-oob='true'><ul>{ordered}</ul></div>"
    return HttpResponse(mark_safe(resp_str))


def mark_order_form_submissions_paid(request):
    return _change_order_form_submission_status(request, "mark_paid")


def mark_order_form_submissions_shipped(request):
    return _change_order_form_submission_status(request, "mark_shipped")


def reset_order_form_submissions(request):
    return _change_order_form_submission_status(request, "reset")


def _change_order_form_submission_status(request, update_function):
    submission_ids = request.GET.getlist("selected-submissions")
    submissions = OrderFormSubmission.objects.filter(id__in=submission_ids)
    for submission in submissions:
        getattr(submission, update_function)()
    resp = HttpResponse()
    resp.headers["HX-Refresh"] = "true"
    return resp


def order_detail(request, reference):
    submission = get_object_or_404(OrderFormSubmission, reference=reference)
    context = {
        "page": submission.page.orderformpage, 
        "title": submission.page.orderformpage.subject_title, 
        "form_submission": submission, 
        "total": submission.cost
    }

    if not submission.paid:
        context["paypal_form"] = get_paypal_form(
            request=request,
            amount=submission.cost, 
            item_name=f"Order form submission: {submission.page.title}",
            reference=submission.reference
        )
    return TemplateResponse(request, "home/order_form_page_landing.html", context)


def pdf_form_detail(request, reference):
    submission = get_object_or_404(PDFFormSubmission, reference=reference)
    
    if not request.user.is_authenticated or not request.user.is_staff:
        # Staff users can access without token.
        # For anyone else, check for valid, non-expired token
        token = request.GET.get("token")
        if not submission.token_active(token):
            return redirect(submission.get_request_token_url())

    if submission.is_draft:
        messages.error(
            request, 
            "This form has not yet been submitted."
        )
    context = {"page": submission.page.formpage.pdfformpage, "submission": submission}
    return TemplateResponse(request, "home/pdf_form_detail.html", context)


class TokenRequestForm(forms.Form):

    email = forms.EmailField()

    def __init__(self, *args, **kwargs):
        self.submission = kwargs.pop("submission")
        super().__init__(*args, **kwargs)
    
    def clean_email(self):
        if self.cleaned_data["email"] != self.submission.email:
            self.add_error(
                "email", 
                "Email address does not match submission. Please ensure you "
                "enter the same email address you used previously."
            )

    
def pdf_form_token_request(request, reference):
    submission = get_object_or_404(PDFFormSubmission, reference=reference)
    context = {"submission": submission}
    if request.POST:
        form = TokenRequestForm(request.POST, submission=submission)
        if form.is_valid():
            submission.reset_token()
            send_mail(
                f"Access link for {submission.page.title} {submission.reference}",
                f"You can access your submission at https://{settings.DOMAIN}{submission.get_absolute_url_with_token()}\n"
                f"This link will expire in 15 minutes.",
                [submission.email],
                settings.DEFAULT_FROM_EMAIL,
            )
            context["token_sent"] = True
    else:
        form = TokenRequestForm(submission=submission)
    context["form"] = form
    return TemplateResponse(request, "home/pdf_form_token_request.html", context=context)


def pdf_form_download(request, pk):
    submission = get_object_or_404(PDFFormSubmission, pk=pk)
    pdf_filehandle = generate_pdf(submission)
    
    return FileResponse(
        pdf_filehandle, 
        as_attachment=True, 
        content_type="application/pdf",
        filename=submission.get_download_filename()
    )


def merch_info(request):
    return TemplateResponse(request, "home/merch_info.html")
