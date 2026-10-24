from django.contrib import admin
from salesman.admin.admin import BaseOrderAdmin, OrderItemInline

from .models import Order


class ShopOrderItemInline(OrderItemInline):
    fields = [
        *OrderItemInline.fields,
        "dispatcher_name",
        "shipping_status",
        "shipped_at",
        "shipped_by",
    ]
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(BaseOrderAdmin):
    """
    Salesman's Django admin for orders, for tech admins to check orders' fields
    (shop admins use the orders admin in Wagtail, see admin_orders.py). Refunds
    are made in the Wagtail orders admin.
    """

    list_display = [*BaseOrderAdmin.list_display[:2], "name", *BaseOrderAdmin.list_display[2:]]
    search_fields = [*BaseOrderAdmin.search_fields, "name"]
    readonly_fields = [*BaseOrderAdmin.readonly_fields, "name", "shipping_method"]
    inlines = [
        ShopOrderItemInline if inline is OrderItemInline else inline
        for inline in BaseOrderAdmin.inlines
    ]
