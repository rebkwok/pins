from datetime import datetime, UTC
from io import StringIO

import pytest
from model_bakery import baker

from django.core.management import call_command

from salesman.core.utils import get_salesman_model

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")


def test_clear_expired_baskets_command(freezer, basket):
    freezer.move_to("2024-01-01 10:00")
    basket.timeout = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    basket.save()
    freezer.move_to("2023-12-01 10:00")
    stale_basket = baker.make("shop.Basket")
    freezer.move_to("2024-01-01 10:00")

    out = StringIO()
    call_command("clear_expired_baskets", stdout=out)

    assert not basket.items.exists()
    assert not Basket.objects.filter(id=stale_basket.id).exists()
    assert out.getvalue().strip() == (
        "Cleared 1 expired basket(s); deleted 1 stale empty basket(s)"
    )
