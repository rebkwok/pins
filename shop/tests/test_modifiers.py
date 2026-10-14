from decimal import Decimal
import pytest
from model_bakery import baker

from ..models import Sale

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
    assert basket_item.subtotal == Decimal("20.00")
    assert basket_item.total == Decimal("19.00")
    assert basket_item.extra_rows["sales-discount"].data == {
        "label": "Sale: 20% off",
        "amount": "-1.00",
        "extra": {},
    }
