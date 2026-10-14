from django.http import HttpRequest
from salesman.basket.models import BaseBasket
from salesman.basket.modifiers import BasketModifier

from .models import Sale


class ShippingCostModifier(BasketModifier):
    """
    Add flat shipping cost to the basket.
    """

    identifier = "shipping-cost"

    def process_basket(self, basket, request):
        if basket.shipping_method != "collect" and basket.count:
            self.add_extra_row(basket, request, label="Shipping", amount=3.99)


class SaleModifier(BasketModifier):
    """
    Apply sales
    """

    identifier = "sales-discount"

    def process_item(self, item, request):
        sale_item = item.product.get_sale_item()
        if sale_item:
            # check if current item (BasketItem) is in the sale (check by product first, then category)
            item_discount = sale_item.discount
            label = f"Sale: {item_discount}% off"
            discount_amount = item.total / -item_discount
            self.add_extra_row(item, request, label, discount_amount)
