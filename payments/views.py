from django.shortcuts import render, HttpResponse

from django.views.decorators.csrf import csrf_exempt
from fundraising.models import RecipeBookSubmission

@csrf_exempt
def paypal_return(request):
    paypal_item_reference = request.session.get("paypal_item_reference")
    context = {}
    try:
        # TODO Find Recipe Book Submission OR OrderFormSubmission with this reference
        context["submission"] = RecipeBookSubmission.objects.get(pk=paypal_item_reference)
    except RecipeBookSubmission.DoesNotExist:
        ...
    return render(request, "payments/paypal_return.html", context)


@csrf_exempt
def payment_cancel(request):
    submission = request.session.get("paypal_item_reference")
    return render(request, "payments/paypal_cancel.html", {"paypal_item_reference": submission})


