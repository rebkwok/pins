from django.conf import settings
from salesman.basket.modifiers import BasketModifier

from .models import Sale


class ShippingCostModifier(BasketModifier):
    """
    Add flat shipping cost (settings.SHOP_SHIPPING_COST) to baskets that are
    delivered.
    """

    identifier = "shipping-cost"

    def process_basket(self, basket, request):
        if basket.needs_delivery and basket.count:
            self.add_extra_row(
                basket, request, label="Shipping", amount=settings.SHOP_SHIPPING_COST
            )


class SaleModifier(BasketModifier):
    """
    Apply sales
    """

    identifier = "sales-discount"

    def process_item(self, item, request):
        sale_item = item.product.get_sale_item()
        if sale_item:
            # check if current item (BasketItem) is in the sale (check by product first, then category)
            label = f"Sale: {sale_item.discount}% off"
            discount_amount = (
                -item.product.get_discount_amount(sale_item) * item.quantity
            )
            self.add_extra_row(item, request, label, discount_amount)
