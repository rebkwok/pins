from django.urls import path

from .views import (
    ProductDetailView,
    add_to_basket,
    basket_view,
    basket_timeout,
    checkout_view,
    decrease_quantity,
    delete_basket_item,
    increase_quantity,
    new_order_view,
    order_status_view,
    update_quantity,
)


app_name = "shop"
urlpatterns = [
    path(
        "product/<pk>/",
        ProductDetailView.as_view(),
        name="product_detail",
    ),
    path("quantity/dec/<int:product_id>", decrease_quantity, name="decrease_quantity"),
    path("quantity/inc/<int:product_id>", increase_quantity, name="increase_quantity"),
    path("basket/add/<int:product_id>", add_to_basket, name="add_to_basket"),
    path("basket/update/<str:ref>", update_quantity, name="update_quantity"),
    path("basket/delete/<str:ref>", delete_basket_item, name="delete_basket_item"),
    path("basket/", basket_view, name="basket"),
    path("basket-timeout/<int:basket_id>", basket_timeout, name="basket_timeout"),
    path("checkout/", checkout_view, name="checkout"),
    path("order/<str:token>/new/", new_order_view, name="new_order_status"),
    path("order/<str:token>/", order_status_view, name="order_status"),
]
