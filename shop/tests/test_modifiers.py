from decimal import Decimal
import pytest
from model_bakery import baker

from ..models import Product, Sale, SaleProduct, ShippingRate

pytestmark = pytest.mark.django_db


def test_basket_shipping_modifier(basket):
    assert basket.extra_rows == {}
    assert basket.subtotal == 20
    assert basket.total == 20

    basket.shipping_method = "deliver"
    basket.save()
    basket.update(request=None)

    assert list(basket.extra_rows.keys()) == ["shipping-cost"]
    assert basket.extra_rows["shipping-cost"].data == {
        "label": "Shipping",
        "amount": "4.99",
        "extra": {},
    }
    assert basket.subtotal == 20
    assert basket.total == Decimal("24.99")


def add_product(basket, rate=None, requires_shipping=True):
    product = baker.make(
        Product, price=1, shipping_rate=rate, requires_shipping=requires_shipping
    )
    basket.add(baker.make("shop.ProductVariant", product=product, stock=5))


def shipping(basket):
    basket.shipping_method = "deliver"
    basket.save()
    basket.update(request=None)
    return basket.extra_rows["shipping-cost"].data["amount"]


def test_basket_shipping_highest_rate(basket):
    # the basket's product has the default rate (Standard, £4.99)
    small = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    large = ShippingRate.objects.create(name="Large items", amount=Decimal("7.00"))
    basket.clear()
    add_product(basket, small)
    assert shipping(basket) == "3.50"
    add_product(basket, small)
    # once, not per item
    assert shipping(basket) == "3.50"
    add_product(basket, large)
    assert shipping(basket) == "7.00"
    assert basket.total == Decimal("10.00")


def test_basket_shipping_ignores_products_not_shipped(basket):
    small = ShippingRate.objects.create(name="Small items", amount=Decimal("3.50"))
    basket.clear()
    add_product(basket, small)
    # (a product that doesn't need shipping keeps any rate it had)
    add_product(basket, ShippingRate.get_default(), requires_shipping=False)
    assert shipping(basket) == "3.50"


def test_basket_shipping_product_without_rate(basket):
    # e.g. a product saved before it had a rate: the default rate
    ShippingRate.objects.update(amount=Decimal("5.50"))
    Product.objects.update(shipping_rate=None)
    # (reloaded, as its items are cached with their products)
    assert shipping(reload(basket)) == "5.50"


def test_basket_shipping_no_rates(basket):
    Product.objects.update(shipping_rate=None)
    ShippingRate.objects.all().delete()
    assert shipping(reload(basket)) == "0.00"


def reload(basket):
    return type(basket).objects.get(pk=basket.pk)


def test_basket_shipping_modifier_empty_basket(basket):
    basket.shipping_method = "deliver"
    basket.save()
    basket.clear()
    basket.update(request=None)
    assert basket.extra_rows == {}


def test_sale_modifier(freezer, sale_with_items, basket):
    # make sure sale is current
    freezer.move_to("2022-01-01 09:00")
    assert Sale.current_sale() == sale_with_items
    basket_item = basket.items.first()
    basket_item.update(request=None)
    # 2 x £10 at 20% off
    assert basket_item.subtotal == Decimal("20.00")
    assert basket_item.total == Decimal("16.00")
    assert basket_item.extra_rows["sales-discount"].data == {
        "label": "Sale: 20% off",
        "amount": "-4.00",
        "extra": {},
    }


@pytest.mark.parametrize(
    "discount,expected_total",
    [
        (10, Decimal("18.00")),
        (20, Decimal("16.00")),
        (50, Decimal("10.00")),
        (100, Decimal("0.00")),
    ],
)
def test_sale_modifier_discount_percentages(
    freezer, sale_with_items, basket, discount, expected_total
):
    freezer.move_to("2022-01-01 09:00")
    SaleProduct.objects.filter(sale=sale_with_items).update(discount=discount)
    basket_item = basket.items.first()
    basket_item.update(request=None)
    assert basket_item.total == expected_total


def test_sale_modifier_product_excluded_from_sale(freezer, sale_with_items, basket):
    # A product discount of 0 excludes the product, even though its category is on sale
    freezer.move_to("2022-01-01 09:00")
    SaleProduct.objects.filter(sale=sale_with_items).update(discount=0)
    basket_item = basket.items.first()
    basket_item.update(request=None)
    assert "sales-discount" not in basket_item.extra_rows
    assert basket_item.total == Decimal("20.00")


def test_sale_modifier_matches_displayed_price(freezer, sale_with_items, basket):
    # 15% off £1.10 is £0.165, rounded to £0.17, so displayed as £0.93 each.
    # The basket must charge 3 x £0.93 = £2.79, not 15% off the £3.30 line
    # total (£2.80)
    freezer.move_to("2022-01-01 09:00")
    SaleProduct.objects.filter(sale=sale_with_items).update(discount=15)
    basket_item = basket.items.first()
    variant = basket_item.product
    variant.price = Decimal("1.10")
    variant.save()
    basket_item.quantity = 3
    basket_item.save()
    basket_item.update(request=None)

    assert variant.get_discounted_price() == Decimal("0.93")
    assert basket_item.total == Decimal("2.79")


@pytest.mark.parametrize("shipping_method,needs_delivery", [("collect", False), ("deliver", True)])
def test_needs_delivery(basket, order, shipping_method, needs_delivery):
    basket.shipping_method = shipping_method
    order.shipping_method = shipping_method
    assert basket.needs_delivery == needs_delivery
    assert order.needs_delivery == needs_delivery

