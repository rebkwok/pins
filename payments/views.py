from django.shortcuts import render, HttpResponse

from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def paypal_return(request):
    return render(request, "payments/paypal_return.html")


@csrf_exempt
def payment_cancel(request):
    return render(request, "payments/paypal_cancel.html")


