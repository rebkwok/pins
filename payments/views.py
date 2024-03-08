from django.shortcuts import render, HttpResponse

from django.views.decorators.csrf import csrf_exempt
from fundraising.models import RecipeBookSubmission
from home.models import OrderFormSubmission


def _get_context(request):
    paypal_item_reference = request.session.get("paypal_item_reference")
    context = {}
    try:
        context["item"] = RecipeBookSubmission.objects.get(pk=paypal_item_reference)
        context["item_type"] = "submission"
    except RecipeBookSubmission.DoesNotExist:
        try:
            context["item"] = OrderFormSubmission.objects.get(reference=paypal_item_reference)
            context["item_type"] = "order"
        except OrderFormSubmission.DoesNotExist:
            ...
    return context

@csrf_exempt
def paypal_return(request):
    return render(request, "payments/paypal_return.html", _get_context(request))


@csrf_exempt
def payment_cancel(request):
    return render(request, "payments/paypal_cancel.html", _get_context(request))


