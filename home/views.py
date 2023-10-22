from django.shortcuts import get_object_or_404
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.safestring import mark_safe

from .models import OrderFormPage, OrderFormSubmission



def calculate_order_total_view(request, order_page_id):
    order_page = get_object_or_404(OrderFormPage, pk=order_page_id)
    _, total = order_page.get_variant_quantities_and_total(dict(request.POST))
    
    resp_str = f"<span id='order-total'>{total}</span>"
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


def mark_order_form_submissions_paid_and_shipped(request):
    return _change_order_form_submission_status(request, "mark_paid_and_shipped")


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
