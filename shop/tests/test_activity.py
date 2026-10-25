"""The shop's activity log (activity.py): what's logged, by whom, and its messages"""

import html
from decimal import Decimal

import pytest
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model
from wagtail.log_actions import registry as log_registry
from wagtail.models import ModelLogEntry

from salesman_stripe_connect import signals as stripe_signals

from .. import activity
from ..models import DISPATCHERS_GROUP, OrderItem, Product
from ..payment import PayByStripe

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")


@pytest.fixture
def admin(client):
    user = baker.make("auth.User", is_superuser=True, is_staff=True, first_name="Ann", last_name="Admin")
    client.force_login(user)
    return user


@pytest.fixture
def paid_order(order):
    order.status = Order.Status.PROCESSING
    order.save()
    order.pay(amount=order.total, transaction_id="pi_1", payment_method="stripe")
    return order


def entries(obj, action=None):
    logs = log_registry.get_logs_for_instance(obj).order_by("timestamp", "pk")
    return list(logs.filter(action=action) if action else logs)


def messages(obj):
    return [entry.message for entry in entries(obj)]


# Orders: placed and paid (at checkout, or from the Stripe webhook)


def test_order_placed_and_paid(paid_order):
    (placed,) = entries(paid_order, activity.ORDER_PLACED)
    assert placed.message == "Order placed (£20.00)"
    assert placed.user is None
    (paid,) = entries(paid_order, activity.ORDER_PAID)
    assert paid.message == "Paid £20.00"


def test_refund_logged_once(paid_order):
    # refunds are payments with negative amounts: logged as refunds, not payments
    PayByStripe.record_refund(paid_order, "re_1", Decimal("5.00"))
    PayByStripe.record_refund(paid_order, "re_1", Decimal("5.00"))
    assert len(entries(paid_order, activity.ORDER_PAID)) == 1
    (refund,) = entries(paid_order, activity.ORDER_REFUNDED)
    assert refund.message == "Refunded £5.00 (part of the order)"
    PayByStripe.record_refund(paid_order, "re_2", Decimal("15.00"))
    assert entries(paid_order, activity.ORDER_REFUNDED)[-1].message == "Refunded £15.00 (the whole order)"


def test_disputes(paid_order):
    stripe_signals.dispute_created.send(sender=None, order=paid_order, dispute=None, message="Disputed: fraudulent")
    stripe_signals.dispute_closed.send(sender=None, order=paid_order, dispute=None, message="The dispute was won.")
    assert messages(paid_order)[-2:] == ["Disputed: fraudulent", "The dispute was won."]


# Orders: our actions


def test_items_shipped_and_not_sent(paid_order, admin):
    item = paid_order.items.get()
    paid_order.mark_items_shipped([item], admin)
    (entry,) = entries(paid_order, activity.ORDER_SHIPPED)
    assert entry.user == admin
    # (the order fixture is collected)
    assert entry.message == f"Marked collected: 2 × {item.name}"
    paid_order.shipping_method = "deliver"
    paid_order.save()
    item.shipping_status = OrderItem.TO_SEND
    item.save()
    paid_order.mark_items_not_sent([item], admin)
    assert entries(paid_order, activity.ORDER_NOT_SENT)[0].message == f"Marked won't be sent: 2 × {item.name}"
    # nothing changed (already marked): nothing logged
    paid_order.mark_items_shipped([item], admin)
    assert len(entries(paid_order, activity.ORDER_SHIPPED)) == 1


def test_shipped_message_delivered(paid_order, admin):
    paid_order.shipping_method = "deliver"
    paid_order.save()
    item = paid_order.items.get()
    paid_order.mark_items_shipped([item], admin)
    assert entries(paid_order, activity.ORDER_SHIPPED)[0].message.startswith("Marked shipped: ")


def test_note_complete_and_cancel_from_admin(client, admin, paid_order):
    client.post(reverse("shop_orders:edit", args=(paid_order.pk,)), {"message": "Customer called " + "x" * 120})
    (note,) = entries(paid_order, activity.ORDER_NOTE)
    assert note.user == admin
    assert note.message.startswith("Added a note: Customer called x")
    assert note.message.endswith("…")
    paid_order.items.update(shipping_status=OrderItem.SHIPPED)
    paid_order.status = Order.Status.SHIPPED
    paid_order.save()
    client.post(reverse("shop_orders:complete", args=(paid_order.pk,)))
    assert entries(paid_order, activity.ORDER_COMPLETED)[0].message == "Marked completed"


def test_cancel_from_admin(client, admin, order):
    client.post(reverse("shop_orders:cancel", args=(order.pk,)))
    (entry,) = entries(order, activity.ORDER_CANCELLED)
    assert (entry.user, entry.message) == (admin, "Cancelled")


def test_order_page_activity(client, admin, paid_order):
    paid_order.mark_items_shipped(list(paid_order.items.all()), admin)
    content = " ".join(html.unescape(client.get(reverse("shop_orders:edit", args=(paid_order.pk,))).content.decode()).split())
    assert "<h2 class=\"w-h3\">Activity</h2>" in content
    # oldest first; checkout and the webhook have no user
    assert "<td>Customer / Stripe</td> <td>Order placed (£20.00)</td>" in content
    assert "<td>Ann Admin</td> <td>Marked collected: 2 ×" in content
    assert content.index("Order placed") < content.index("Marked collected")


def test_order_page_no_activity(client, admin, order):
    ModelLogEntry.objects.all().delete()
    content = client.get(reverse("shop_orders:edit", args=(order.pk,))).content.decode()
    assert "No activity yet." in content


# Dispatchers and the shop's setup


def test_dispatcher_added_and_removed(client, admin):
    user = baker.make("auth.User", first_name="Dee", last_name="Spatcher")
    client.post(reverse("shop_dispatchers:index"), {"user": user.pk})
    client.post(reverse("shop_dispatchers:index"), {"remove": user.pk})
    assert [(entry.user, entry.message) for entry in entries(user)] == [
        (admin, "Added as a dispatcher"),
        (admin, "Removed as a dispatcher"),
    ]
    assert not user.groups.filter(name=DISPATCHERS_GROUP).exists()


def test_category_products_reordered(client, admin, category):
    baker.make(Product, name="Mug", category=category)
    cup = baker.make(Product, name="Cup", category=category)
    url = reverse("shop_category_products_reorder", args=(category.pk, cup.pk))
    client.post(f"{url}?position=0")
    (entry,) = entries(category, activity.CATEGORY_REORDERED)
    assert (entry.user, entry.message) == (admin, "Moved Cup to position 1")


def test_formatters_without_data(order):
    # (e.g. an entry logged without data)
    entry = activity.log_order(order, activity.ORDER_PAID)
    assert entry.message == "Paid £0.00"
    assert activity.gbp(None) == "£0.00"
