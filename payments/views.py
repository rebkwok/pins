from django.shortcuts import render, HttpResponse

from django.views.decorators.csrf import csrf_exempt
from fundraising.models import RecipeBookSubmission

@csrf_exempt
def paypal_return(request):
    submission_ref = request.session.get("submission_ref")
    context = {}
    try:
        context["submission"] = RecipeBookSubmission.objects.get(pk=submission_ref)
    except RecipeBookSubmission.DoesNotExist:
        ...
    return render(request, "payments/paypal_return.html", context)


@csrf_exempt
def payment_cancel(request):
    submission = request.session.get("submission_ref")
    return render(request, "payments/paypal_cancel.html", {"submission_ref": submission})


