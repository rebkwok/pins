from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from .models import OrderFormPage


def calculate_order_total_view(request, order_page_id):
    order_page = get_object_or_404(OrderFormPage, pk=order_page_id)
    _, total = order_page.get_variant_quantities_and_total(dict(request.POST))

    return HttpResponse(total)
