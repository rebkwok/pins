import re

from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe

from .models import OrderFormPage, OrderFormSubmission
from payments.utils import get_paypal_form


def calculate_order_total_view(request, order_page_id):
    order_page = get_object_or_404(OrderFormPage, pk=order_page_id)
    _, total, discount = order_page.get_variant_quantities_and_total(dict(request.POST))
    discount_str = f" (discount £{discount})" if discount else ""
    resp_str = f"<span id='order-total'>{total}{discount_str}</span>"
    
    if request.POST.get("voucher_code").strip() and not discount:
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
        "title": submission.page.subject_title, 
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