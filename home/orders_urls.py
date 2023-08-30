from django.urls import include, path

from home.views import calculate_order_total_view

app_name = "orders"
urlpatterns = [
    path("calculate-order-total/<int:order_page_id>/", calculate_order_total_view, name="calculate_order_total")
]
