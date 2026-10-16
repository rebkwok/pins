import pytest
from model_bakery import baker

from salesman.admin.wagtail_hooks import OrderAdmin as SalesmanOrderAdmin
from salesman.orders.serializers import OrderSerializer as SalesmanOrderSerializer

from ..wagtail_hooks import OrderAdmin

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    yield client


def contact_panel_fields(panels):
    return [child.attr for child in panels[2].children]


def test_order_admin_adds_name_and_shipping_method():
    assert OrderAdmin.list_display == [
        "__str__",
        "email",
        "name",
        "status_display",
        "shipping_method",
        "total_display",
        "is_paid_display",
        "date_created",
    ]
    assert OrderAdmin.search_fields == ["ref", "email", "token", "name"]
    assert contact_panel_fields(OrderAdmin.default_panels) == [
        "customer_display",
        "email",
        "name",
        "shipping_method",
        "shipping_address_display",
        "billing_address_display",
    ]


def test_salesman_order_admin_and_serializer_not_changed():
    # The shop's order admin doesn't change salesman's lists and panels
    assert "name" not in SalesmanOrderAdmin.list_display
    assert "shipping_method" not in SalesmanOrderAdmin.list_display
    assert "name" not in SalesmanOrderAdmin.search_fields
    assert contact_panel_fields(SalesmanOrderAdmin.default_panels) == [
        "customer_display",
        "email",
        "shipping_address_display",
        "billing_address_display",
    ]
    assert "name" not in SalesmanOrderSerializer.Meta.fields


def test_order_admin_index(admin_client, order):
    url = OrderAdmin().url_helper.index_url
    resp = admin_client.get(url, {"q": "Test User"})
    assert resp.status_code == 200
    content = resp.content.decode()
    assert order.ref in content
    assert "Collect in store" in content


def test_order_admin_edit(admin_client, order):
    url = OrderAdmin().url_helper.get_action_url("edit", order.pk)
    resp = admin_client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Test User" in content
    assert "Collect in store" in content
