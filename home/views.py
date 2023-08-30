from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from .models import OrderFormPage


def calculate_order_total_view(request, order_page_id):

    order_page = get_object_or_404(OrderFormPage, pk=order_page_id)
    quantity = int(request.POST.get('quantity', 1))
    total = str((order_page.product_cost * quantity) + order_page.shipping_cost)
    request.session["total"] = total
    return HttpResponse(total)
