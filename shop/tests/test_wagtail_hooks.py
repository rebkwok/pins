import re
from decimal import Decimal

import pytest
from model_bakery import baker

from salesman.admin.wagtail_hooks import OrderAdmin as SalesmanOrderAdmin
from salesman.core.utils import get_salesman_model
from salesman.orders.serializers import OrderSerializer as SalesmanOrderSerializer

from ..wagtail_hooks import OrderAdmin

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")


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
        "refunds_list_display",
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
    assert "Collect in person" in content


def test_order_admin_edit(admin_client, order):
    url = OrderAdmin().url_helper.get_action_url("edit", order.pk)
    resp = admin_client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Test User" in content
    assert "Collect in person" in content


def panel_fields(panels, index):
    return [
        getattr(child, "attr", None) or child.field_name
        for child in panels[index].children
    ]


def test_order_admin_adds_refunds():
    # Status
    assert panel_fields(OrderAdmin.default_panels, 1) == [
        "status",
        "date_created",
        "date_updated",
        "is_paid",
        "refunds_display",
    ]
    # Totals
    assert panel_fields(OrderAdmin.default_panels, 3) == [
        "subtotal_display",
        "extra_rows_display",
        "total_display",
        "amount_paid_display",
        "refunds_display",
        "amount_outstanding_display",
    ]
    assert "refunds_display" not in panel_fields(SalesmanOrderAdmin.default_panels, 3)


def field_values(content):
    """The admin page's read-only fields, as {label: value}"""
    fields = re.findall(
        r'<h3 class="w-field__label">(.*?)</h3>\s*<div>(.*?)</div>', content, re.S
    )
    return {label.strip(): value.strip() for label, value in fields}


@pytest.mark.parametrize(
    "refunds,paid_icon,refunded,outstanding",
    [
        ([], "icon-tick", "-", "0.00"),
        (["-5.00"], "icon-tick", "5.00 (partially refunded)", "0.00"),
        (["-5.00", "-15.00"], "icon-tick", "20.00 (fully refunded)", "0.00"),
    ],
)
def test_order_admin_edit_refunds(admin_client, order, refunds, paid_icon, refunded, outstanding):
    # order total is £20
    order.pay(amount=Decimal("20.00"), transaction_id="pi_1")
    for index, amount in enumerate(refunds):
        order.pay(amount=Decimal(amount), transaction_id=f"re_{index}")
    url = OrderAdmin().url_helper.get_action_url("edit", order.pk)
    values = field_values(admin_client.get(url).content.decode())
    # refunds don't make the order unpaid or outstanding
    assert paid_icon in values["Is paid"]
    assert values["Amount paid"] == "20.00"
    assert values["Refunded"] == refunded
    assert values["Amount outstanding"] == outstanding


def test_order_admin_edit_unpaid(admin_client, order):
    url = OrderAdmin().url_helper.get_action_url("edit", order.pk)
    values = field_values(admin_client.get(url).content.decode())
    assert "icon-cross" in values["Is paid"]
    assert values["Amount paid"] == "0.00"
    assert values["Amount outstanding"] == "20.00"


@pytest.fixture
def refunded_orders(basket):
    # unpaid, paid, partially refunded and fully refunded orders (totals £20)
    orders = [Order.objects.create_from_basket(basket, request=None) for _ in range(4)]
    for order in orders[1:]:
        order.pay(amount=Decimal("20.00"), transaction_id=f"pi_{order.id}")
    orders[2].pay(amount=Decimal("-5.00"), transaction_id="re_1")
    orders[3].pay(amount=Decimal("-20.00"), transaction_id="re_2")
    yield orders


def test_order_admin_index_refunds(admin_client, refunded_orders):
    resp = admin_client.get(OrderAdmin().url_helper.index_url)
    content = resp.content.decode()
    assert re.search(r"<th[^>]*>\s*Refunds", content)
    # in the column, and in the filter
    assert content.count("Partially refunded") == 2
    assert content.count("Fully refunded") == 2


@pytest.mark.parametrize(
    "value,expected", [("partial", [2]), ("full", [3]), ("none", [0, 1]), ("", [0, 1, 2, 3])]
)
def test_order_admin_refunds_filter(admin_client, refunded_orders, value, expected):
    resp = admin_client.get(OrderAdmin().url_helper.index_url, {"refunds": value})
    shown = set(resp.context["object_list"])
    assert shown == {refunded_orders[index] for index in expected}
