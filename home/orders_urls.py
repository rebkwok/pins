from django.urls import include, path

from home.views import (
    calculate_order_total_view, 
    mark_order_form_submissions_paid,
    mark_order_form_submissions_shipped,
    reset_order_form_submissions,
    order_detail,
)

app_name = "orders"
urlpatterns = [
    path(
        "calculate-order-total/<int:order_page_id>/", 
        calculate_order_total_view, 
        name="calculate_order_total"
    ),
    path(
        "mark-orders-paid/", 
        mark_order_form_submissions_paid, 
        name="mark_order_form_submissions_paid"
    ),
    path(
        "mark-orders-shipped/", 
        mark_order_form_submissions_shipped, 
        name="mark_order_form_submissions_shipped"
    ),
    path(
        "reset-orders/", 
        reset_order_form_submissions, 
        name="reset_order_form_submissions"
    ),
    path(
        "<str:reference>/",
        order_detail,
        name="order_detail",
    )
]
