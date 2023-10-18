from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.safestring import mark_safe
from .models import OrderFormPage


def calculate_order_total_view(request, order_page_id):
    order_page = get_object_or_404(OrderFormPage, pk=order_page_id)
    _, total = order_page.get_variant_quantities_and_total(dict(request.POST))
    
    resp_str = f"<span id='order-total'>{total}</span>"
    # check quantities are allowed
    allowed = True
    if order_page.total_available:
        total_ordered_so_far = order_page.get_total_quantity_ordered()
        total_for_this_order = order_page.quantity_ordered_by_submission(dict(request.POST))
        remaining_stock = order_page.total_available - total_ordered_so_far
        allowed = total_for_this_order <= remaining_stock
    
    if not allowed:
        resp_str += f"""
            <div id='not-allowed' hx-swap-oob='true' class='text-danger'>
            Quantity selected is unavailable; please select a maximum of {remaining_stock} total items.
            </div>
        """
    else:
        resp_str += "<div id='not-allowed' hx-swap-oob='true'></div>"

    return HttpResponse(mark_safe(resp_str))
