from decimal import Decimal

from salesman.basket.modifiers import BasketModifier

from .models import (
    DISCOUNT_CODE_INVALID,
    DISCOUNT_CODE_TOO_LITTLE_LEFT,
    DISCOUNT_ROW,
    MIN_CARD_PAYMENT,
    Sale,
    ShippingRate,
)


class ShippingCostModifier(BasketModifier):
    """
    Add the shipping cost to baskets that are delivered: the highest shipping
    rate of the basket's products that need shipping, charged once.
    """

    identifier = "shipping-cost"

    def process_basket(self, basket, request):
        if basket.needs_delivery and basket.count:
            self.add_extra_row(
                basket, request, label="Shipping", amount=basket_shipping_cost(basket)
            )


def basket_shipping_cost(basket):
    """
    The highest shipping rate of the basket's products that need shipping (the
    default rate for a product without one, or nothing if there are no rates)
    """
    rates = []
    for item in basket.get_items():
        product = item.product.product if item.product is not None else None
        if product is not None and product.requires_shipping:
            rates.append(product.shipping_rate or ShippingRate.get_default())
    return max((rate.amount for rate in rates if rate is not None), default=Decimal(0))


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


class DiscountModifier(BasketModifier):
    """
    Apply the basket's discount code, as an amount off the whole basket
    (including shipping, and after sale prices). Never takes the total below
    zero, and isn't applied if it would leave less than a card payment's minimum
    to pay.

    Sets basket.discount_problem (why the code isn't applied, or None) and
    basket.discount_unused (the code's value left over if it covers the whole
    basket), for the basket page.
    """

    identifier = DISCOUNT_ROW

    def finalize_basket(self, basket, request):
        # After the other modifiers' rows (e.g. shipping) have been added
        basket.discount_problem = None
        basket.discount_unused = Decimal(0)
        if not basket.extra.get(basket.DISCOUNT_CODE_KEY) or not basket.count:
            return
        code = basket.discount_code
        problem = DISCOUNT_CODE_INVALID if code is None else code.unavailable_reason(basket)
        if problem is None:
            amount = min(code.amount, basket.total)
            if 0 < basket.total - amount < MIN_CARD_PAYMENT:
                problem = DISCOUNT_CODE_TOO_LITTLE_LEFT
        if problem is not None:
            basket.discount_problem = problem
            return
        self.add_extra_row(
            basket,
            request,
            label=f"Discount code {code.code}",
            amount=-amount,
            extra={"code": code.code},
        )
        basket.discount_unused = code.amount - amount
