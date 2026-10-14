from datetime import datetime, UTC

import pytest

from django.utils import timezone

pytestmark = pytest.mark.django_db


def test_basket_middleware(client, basket):
    client.get("/")
    assert basket.items.exists()
    # make other basket expired
    basket.timeout = datetime(2020, 3, 1, tzinfo=UTC)
    basket.save()
    # middleware clears expired basket
    client.get("/")
    assert not basket.items.exists()
