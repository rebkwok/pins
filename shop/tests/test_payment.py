from datetime import datetime, UTC
from urllib.parse import urlparse, parse_qs

import pytest

from django.conf import settings
from django.urls import reverse

from salesman.core.utils import get_salesman_model
from shop.payment import PayInAdvance, PayByStripe, stripe_webhook_view


Basket = get_salesman_model("Basket")

Order = get_salesman_model("Order")

pytestmark = pytest.mark.django_db


def test_pay_in_advance(rf, basket):
    basket_id = basket.id
    request = rf.post("/", {"name": "Test buyer"})
    payment = PayInAdvance()
    redirect_url = payment.basket_payment(basket, request)
    assert not Basket.objects.filter(id=basket.id).exists()

    parsed = urlparse(redirect_url)
    token = parse_qs(parsed.query)["token"][0]
    new_order = Order.objects.get(token=token)
    assert new_order.extra == {"basket_id": basket_id}
    assert new_order.status == "HOLD"


def basket_from_checkout(basket):
    # Add the extra fields that are added by the checkout serializer when
    # basket is progressed to payment
    basket.extra = {
        "basket_id": basket.id,
        "email": "test@test.com",
        "shipping_address": "-",
        "billing_address": "-",
        "payment_method": "stripe",
    }
    return basket


@pytest.fixture
def mock_stripe(requests_mock):
    # mock the stripe requests
    # These are used for basket payment
    requests_mock.post(
        "https://api.stripe.com/v1/customers",
        json={"id": "customer-id-1", "email": "test@test.com"},
    )
    requests_mock.post(
        "https://api.stripe.com/v1/checkout/sessions",
        json={"url": "https://stripe-session-url"},
    )
    # These are used for getting stripe session data
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json={
            "customer": "customer-id-1",
            "amount_total": 2000,
        },
    )
    requests_mock.get(
        "https://api.stripe.com/v1/customers/customer-id-1",
        json={"email": "test@test.com"},
    )


def test_pay_by_stripe(mock_stripe, rf, basket):
    basket = basket_from_checkout(basket)
    request = rf.post("/", {"name": "Test buyer"})
    payment = PayByStripe()
    redirect_url = payment.basket_payment(basket, request)
    assert redirect_url == "https://stripe-session-url"
    assert basket.extra["name"] == "Test buyer"
    # basket still exists - not deleted  and order not created until the webhook is completed
    assert Basket.objects.filter(id=basket.id).exists()


def test_get_stripe_session_data(rf, mock_stripe, basket):
    basket = basket_from_checkout(basket)
    request = rf.post("/", {"name": "Test buyer"})
    payment = PayByStripe()
    assert payment.get_stripe_session_data(basket, request) == {
        "mode": "payment",
        "cancel_url": f"{request.build_absolute_uri()}api/payment/stripe/cancel/",
        "success_url": f"{request.build_absolute_uri()}api/payment/stripe/success/"
        + "?session_id={CHECKOUT_SESSION_ID}",
        "client_reference_id": f"basket_{basket.id}",
        "customer": "customer-id-1",
        "line_items": [
            {
                "price_data": {
                    "currency": "gbp",
                    "unit_amount": 2000,
                    "product_data": {
                        "name": "Purchase 1 items",
                        "description": "2x Test Product - Small",
                    },
                },
                "quantity": 1,
            }
        ],
        "payment_intent_data": {
            "on_behalf_of": settings.STRIPE_CONNECTED_ACCOUNT,
            "transfer_data": {"destination": settings.STRIPE_CONNECTED_ACCOUNT},
        },
        "metadata": {"shipping_method": "collect"},
    }


def test_cancel_view(rf):
    request = rf.get("/")
    resp = PayByStripe.cancel_view(request)
    assert "Your payment was cancelled" in resp.content.decode()


def test_success_view(rf, mock_stripe):
    request = rf.get("/?session_id=test-session")
    resp = PayByStripe.success_view(request)
    content = resp.content.decode()
    assert "You have been charged £20.00" in content
    assert "Your order confirmation has been emailed to test@test.com" in content


# {
#   "id": "evt_1MqqbKLt4dXK03v5qaIbiNCC",
#   "object": "event",
#   "api_version": "2023-10-16",
#   "created": 1680064028,
#   "type": "customer.subscription.updated",
#   "data": {
#     "object": {
#       "id": "sub_1Mqqb6Lt4dXK03v50OA219Ya",
#       "object": "subscription",
#       "application": null,
#       "application_fee_percent": null,
#       "automatic_tax": {
#         "enabled": false
#       },
#       "billing_cycle_anchor": 1680668814,
#       "billing_thresholds": null,
#       "cancel_at": null,
#       "cancel_at_period_end": false,
#       "canceled_at": null,
#       "cancellation_details": {
#         "comment": null,
#         "feedback": null,
#         "reason": null
#       },
#       "collection_method": "charge_automatically",
#       "created": 1680064014,
#       "currency": "usd",
#       "current_period_end": 1683260814,
#       "current_period_start": 1680668814,
#       "customer": "cus_Nc4kL4EPtG5SKe",
#       "days_until_due": null,
#       "default_payment_method": null,
#       "default_source": null,
#       "default_tax_rates": [],
#       "description": "A test subscription",
#       "discount": null,
#       "ended_at": null,
#       "invoice_customer_balance_settings": {
#         "consume_applied_balance_on_void": true
#       },
#       "items": {
#         "object": "list",
#         "data": [
#           {
#             "id": "si_Nc4kEcMHd3vRTS",
#             "object": "subscription_item",
#             "billing_thresholds": null,
#             "created": 1680064014,
#             "metadata": {},
#             "plan": {
#               "id": "price_1Mqqb5Lt4dXK03v5cK9prani",
#               "object": "plan",
#               "active": true,
#               "aggregate_usage": null,
#               "amount": 4242,
#               "amount_decimal": "4242",
#               "billing_scheme": "per_unit",
#               "created": 1680064015,
#               "currency": "usd",
#               "interval": "month",
#               "interval_count": 1,
#               "livemode": false,
#               "metadata": {},
#               "nickname": null,
#               "product": "prod_Nc4kjj2XYpywZV",
#               "tiers": null,
#               "tiers_mode": null,
#               "transform_usage": null,
#               "trial_period_days": null,
#               "usage_type": "licensed"
#             },
#             "price": {
#               "id": "price_1Mqqb5Lt4dXK03v5cK9prani",
#               "object": "price",
#               "active": true,
#               "billing_scheme": "per_unit",
#               "created": 1680064015,
#               "currency": "usd",
#               "custom_unit_amount": null,
#               "livemode": false,
#               "lookup_key": null,
#               "metadata": {},
#               "migrate_to": null,
#               "nickname": null,
#               "product": "prod_Nc4kjj2XYpywZV",
#               "recurring": {
#                 "aggregate_usage": null,
#                 "interval": "month",
#                 "interval_count": 1,
#                 "trial_period_days": null,
#                 "usage_type": "licensed"
#               },
#               "tax_behavior": "unspecified",
#               "tiers_mode": null,
#               "transform_quantity": null,
#               "type": "recurring",
#               "unit_amount": 4242,
#               "unit_amount_decimal": "4242"
#             },
#             "quantity": 1,
#             "subscription": "sub_1Mqqb6Lt4dXK03v50OA219Ya",
#             "tax_rates": []
#           }
#         ],
#         "has_more": false,
#         "total_count": 1,
#         "url": "/v1/subscription_items?subscription=sub_1Mqqb6Lt4dXK03v50OA219Ya"
#       },
#       "latest_invoice": "in_1MqqbILt4dXK03v5cbbciqFZ",
#       "livemode": false,
#       "metadata": {},
#       "next_pending_invoice_item_invoice": null,
#       "on_behalf_of": null,
#       "pause_collection": null,
#       "payment_settings": {
#         "payment_method_options": null,
#         "payment_method_types": null,
#         "save_default_payment_method": "off"
#       },
#       "pending_invoice_item_interval": null,
#       "pending_setup_intent": null,
#       "pending_update": null,
#       "plan": {
#         "id": "price_1Mqqb5Lt4dXK03v5cK9prani",
#         "object": "plan",
#         "active": true,
#         "aggregate_usage": null,
#         "amount": 4242,
#         "amount_decimal": "4242",
#         "billing_scheme": "per_unit",
#         "created": 1680064015,
#         "currency": "usd",
#         "interval": "month",
#         "interval_count": 1,
#         "livemode": false,
#         "metadata": {},
#         "nickname": null,
#         "product": "prod_Nc4kjj2XYpywZV",
#         "tiers": null,
#         "tiers_mode": null,
#         "transform_usage": null,
#         "trial_period_days": null,
#         "usage_type": "licensed"
#       },
#       "quantity": 1,
#       "schedule": null,
#       "start_date": 1680064014,
#       "status": "active",
#       "tax_percent": null,
#       "test_clock": "clock_1Mqqb4Lt4dXK03v5NOFiPg4R",
#       "transfer_data": null,
#       "trial_end": 1680668814,
#       "trial_settings": {
#         "end_behavior": {
#           "missing_payment_method": "create_invoice"
#         }
#       },
#       "trial_start": 1680064014
#     },
#     "previous_attributes": {
#       "current_period_end": 1680668814,
#       "current_period_start": 1680064014,
#       "latest_invoice": "in_1Mqqb6Lt4dXK03v5Xn79tY8i",
#       "status": "trialing"
#     }
#   },
#   "livemode": false,
#   "pending_webhooks": 1,
#   "request": {
#     "id": null,
#     "idempotency_key": null
#   }
# }


from unittest.mock import Mock, patch


@pytest.fixture
def get_mock_stripe_session():
    def stripe_session(**params):
        defaults = {"payment_intent": "payment-intent-id"}
        options = {**defaults, **params}
        return Mock(**options)

    return stripe_session


@pytest.fixture
def get_mock_webhook_event(get_mock_stripe_session):
    def mock_webhook_event(**params):
        webhook_event_type = params.pop(
            "webhook_event_type", "checkout.session.completed"
        )
        mock_event = Mock(
            account=settings.STRIPE_CONNECTED_ACCOUNT,
            data=Mock(object=get_mock_stripe_session(**params)),
            type=webhook_event_type,
        )
        return mock_event

    return mock_webhook_event


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed(mock_webhook, client, basket, get_mock_webhook_event):
    assert not Order.objects.exists()
    basket = basket_from_checkout(basket)
    now = datetime.now(UTC)
    headers = {"STRIPE_SIGNATURE": f"v1=dummy,t={int(now.timestamp())}"}
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id=f"basket_{basket.id}",
        amount_total=basket.total * 100,  # basket total in p for stripe
    )
    resp = client.post(reverse("stripe-webhook"), data={}, headers=headers)
    assert resp.status_code == 200

    assert not Basket.objects.filter(id=basket.id).exists()
    assert Order.objects.count() == 1
    order = Order.objects.first()
    assert order.status == Order.Status.PROCESSING
    assert order.total == 20


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_other_status_ignored(mock_webhook, client, get_mock_webhook_event):
    now = datetime.now(UTC)
    headers = {"STRIPE_SIGNATURE": f"v1=dummy,t={int(now.timestamp())}"}
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        webhook_event_type="checkout.session.unknown",
        client_reference_id=f"basket_1",
        amount_total=1000,  # basket total in p for stripe
    )
    resp = client.post(reverse("shop-stripe-webhook"), data={}, headers=headers)
    assert resp.status_code == 200
    assert resp.content.decode() == "Event ignored"
