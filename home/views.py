from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.safestring import mark_safe
from .models import OrderFormPage


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
