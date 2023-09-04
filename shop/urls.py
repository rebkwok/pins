from django.urls import include, path
from django.views.generic import RedirectView

from .views import (
    ProductCategoryDetailView, 
    decrease_quantity, 
    increase_quantity, 
    add_to_basket,
    update_quantity,
    delete_basket_item,
    basket_view,
    checkout_view,
    copy_shipping_address,
    order_status_view,
    new_order_view,
)


app_name = "shop"
urlpatterns = [
    path("category/<pk>/", ProductCategoryDetailView.as_view(), name="productcategory_detail"),
    path("quantity/dec/<int:product_id>", decrease_quantity, name="decrease_quantity"),
    path("quantity/inc/<int:product_id>", increase_quantity, name="increase_quantity"),
    path("basket/add/<int:product_id>", add_to_basket, name="add_to_basket"),
    path("basket/update/<str:ref>", update_quantity, name="update_quantity"),
    path("basket/delete/<str:ref>", delete_basket_item, name="delete"),
    path("basket/", basket_view, name="basket"),
    path("checkout/copy_shipping_address", copy_shipping_address, name="copy_shipping_address"),
    path("checkout/", checkout_view, name="checkout"),
    path("order/<str:token>/new/", new_order_view, name="new_order_status"),
    path("order/<str:token>/", order_status_view, name="order_status"),
]
