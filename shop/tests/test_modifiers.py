from decimal import Decimal
import pytest
from model_bakery import baker

from ..models import Sale, SaleProduct

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
        "amount": "3.99",
        "extra": {},
    }
    assert basket.subtotal == 20
    assert pytest.approx(basket.total) == Decimal(23.99)


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
