"""
Test mode (SHOP_TEST_MODE): orders numbered TEST-..., and "TEST:" before the
shop's email subjects and order log entries
"""

import pytest
from django.core import mail
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model

from .. import activity
from ..models import generate_order_ref
from .test_shipping import dispatcher, make_dispatcher, make_order, shop_variants  # noqa: F401

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")


def test_order_refs(shop_variants, settings, freezer):
    # the year and the next number; in test mode, TEST- first. The numbers
    # follow on across test and real orders.
    freezer.move_to("2026-06-01")
    mug, card, raffle = shop_variants
    assert make_order([mug]).ref == "2026-00001"
    settings.SHOP_TEST_MODE = True
    assert generate_order_ref(None) == "TEST-2026-00002"
    assert make_order([mug]).ref == "TEST-2026-00002"
    settings.SHOP_TEST_MODE = False
    assert make_order([mug]).ref == "2026-00003"
    # a new year starts again
    freezer.move_to("2027-01-01")
    assert make_order([mug]).ref == "2027-00001"


def test_email_subjects(shop_variants, settings, django_capture_on_commit_callbacks):
    # every shop email (here, the customer's and the shop's for a new order)
    baker.make("shop.ShopSettings", notify_email_addresses="shop@test.com")
    settings.SHOP_TEST_MODE = True
    mug, card, raffle = shop_variants
    with django_capture_on_commit_callbacks(execute=True):
        order = make_order([mug])
    subjects = sorted(email.subject for email in mail.outbox)
    assert subjects == [
        f"TEST: PINS shop order {order.ref} has been received",
        f"TEST: PINS shop order {order.ref}: new order",
    ]
    assert order.ref.startswith("TEST-")


def test_email_subjects_not_test_mode(shop_variants, django_capture_on_commit_callbacks):
    mug, card, raffle = shop_variants
    with django_capture_on_commit_callbacks(execute=True):
        order = make_order([mug])
    (email,) = mail.outbox
    assert email.subject == f"PINS shop order {order.ref} has been received"


def test_order_log_entries(shop_variants, settings, client):
    # order entries logged in test mode start "TEST:" (on the order's page);
    # others don't
    mug, card, raffle = shop_variants
    order = make_order([mug])
    activity.log_order(order, activity.ORDER_NOTE, message="Before")
    settings.SHOP_TEST_MODE = True
    activity.log_order(order, activity.ORDER_NOTE, message="During")
    activity.log_order(order, activity.ORDER_COMPLETED)
    client.force_login(baker.make("auth.User", is_superuser=True))
    content = client.get(reverse("shop_orders:edit", args=(order.pk,))).content.decode()
    assert "<td>Added a note: Before</td>" in content
    assert "<td>TEST: Added a note: During</td>" in content
    assert "<td>TEST: Marked completed</td>" in content


def test_fixed_message_formatters(client):
    # (the actions with a fixed message, e.g. dispatchers added, which aren't
    # orders', so never marked)
    from wagtail.log_actions import registry

    registry.scan_for_actions()
    assert registry.get_action_label(activity.DISPATCHER_ADDED) == "Dispatcher added"
    entry = baker.prepare("wagtailcore.ModelLogEntry", action=activity.DISPATCHER_ADDED, data={})
    assert registry.get_formatter(entry).format_message(entry) == "Added as a dispatcher"
