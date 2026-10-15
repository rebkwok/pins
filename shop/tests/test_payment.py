from datetime import datetime, UTC
from unittest.mock import Mock, patch
from urllib.parse import urlparse, parse_qs

import pytest

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse

from salesman.core.utils import get_salesman_model
from shop.payment import PayInAdvance, PayByStripe, stripe_webhook_view


Basket = get_salesman_model("Basket")

Order = get_salesman_model("Order")
OrderPayment = get_salesman_model("OrderPayment")

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
        json={
            "id": "test-session",
            "object": "checkout.session",
            "url": "https://stripe-session-url",
            # 2024-01-01 10:31 UTC
            "expires_at": 1704105060,
        },
    )
    # This is used for getting stripe session data on the success page
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(),
    )


def stripe_session_data(**params):
    return {
        "id": "test-session",
        "object": "checkout.session",
        "customer": "customer-id-1",
        "customer_details": {"email": "test@test.com"},
        "amount_total": 2000,
        "payment_status": "paid",
        "payment_intent": "payment-intent-id",
        "client_reference_id": "basket_1234",
        **params,
    }


def test_pay_by_stripe(mock_stripe, rf, basket, freezer):
    freezer.move_to("2024-01-01 10:00")
    basket = basket_from_checkout(basket)
    request = rf.post("/", {"name": "Test buyer"})
    payment = PayByStripe()
    redirect_url = payment.basket_payment(basket, request)
    assert redirect_url == "https://stripe-session-url"
    assert basket.extra["name"] == "Test buyer"
    # basket still exists - not deleted  and order not created until the webhook is completed
    assert Basket.objects.filter(id=basket.id).exists()
    # payment has started, so the basket is locked, and its items are held until
    # 5 mins after the session expires
    basket.refresh_from_db()
    assert basket.payment_in_progress
    assert basket.stripe_session_id == "test-session"
    assert basket.stripe_session_url == "https://stripe-session-url"
    assert basket.timeout == datetime(2024, 1, 1, 10, 36, tzinfo=UTC)


def test_get_stripe_session_data(rf, mock_stripe, basket, freezer):
    freezer.move_to("2024-01-01 10:00")
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
        # 31 mins from now
        "expires_at": int(datetime(2024, 1, 1, 10, 31, tzinfo=UTC).timestamp()),
    }


def test_cancel_view(rf):
    request = rf.get("/")
    resp = PayByStripe.cancel_view(request)
    assert "Your payment was cancelled" in resp.content.decode()


def test_success_view(rf, requests_mock, basket):
    basket = basket_from_checkout(basket)
    basket.save()
    session_mock = requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(client_reference_id=f"basket_{basket.id}"),
    )
    request = rf.get("/?session_id=test-session")
    request.user = AnonymousUser()
    resp = PayByStripe.success_view(request)
    content = resp.content.decode()

    # order is fulfilled without waiting for the webhook
    order = Order.objects.get()
    assert order.status == Order.Status.PROCESSING
    assert order.amount_paid == 20
    assert order.extra["stripe_session_id"] == "test-session"
    assert not Basket.objects.filter(id=basket.id).exists()

    assert f"Your order reference is <strong>{order.ref}</strong>" in content
    assert "You have been charged £20.00" in content
    assert "Your order confirmation has been emailed to test@test.com" in content
    assert reverse("shop:order_status", args=(order.token,)) in content
    # basket icon is hidden
    assert "fa-basket-shopping" not in content
    # only the session is retrieved from stripe (no separate customer request)
    assert session_mock.call_count == 1
    assert requests_mock.call_count == 1


@patch("salesman_stripe.payment.stripe.Webhook")
def test_success_view_then_webhook(
    mock_webhook, rf, client, requests_mock, basket, get_mock_webhook_event
):
    basket = basket_from_checkout(basket)
    basket.save()
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(client_reference_id=f"basket_{basket.id}"),
    )
    request = rf.get("/?session_id=test-session")
    request.user = AnonymousUser()
    PayByStripe.success_view(request)

    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        id="test-session",
        client_reference_id=f"basket_{basket.id}",
        amount_total=2000,
    )
    resp = post_webhook(client)
    assert resp.content.decode() == "Order already fulfilled"
    assert Order.objects.count() == 1
    assert OrderPayment.objects.count() == 1


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_then_success_view(
    mock_webhook, rf, client, requests_mock, basket, get_mock_webhook_event
):
    basket = basket_from_checkout(basket)
    basket.save()
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        id="test-session",
        client_reference_id=f"basket_{basket.id}",
        amount_total=2000,
    )
    post_webhook(client)
    order = Order.objects.get()

    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(client_reference_id=f"basket_{basket.id}"),
    )
    request = rf.get("/?session_id=test-session")
    request.user = AnonymousUser()
    content = PayByStripe.success_view(request).content.decode()

    assert f"Your order reference is <strong>{order.ref}</strong>" in content
    assert Order.objects.count() == 1
    assert OrderPayment.objects.count() == 1


def test_success_view_unpaid_session(rf, requests_mock, basket):
    basket = basket_from_checkout(basket)
    basket.save()
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(
            client_reference_id=f"basket_{basket.id}", payment_status="unpaid"
        ),
    )
    request = rf.get("/?session_id=test-session")
    content = PayByStripe.success_view(request).content.decode()

    assert not Order.objects.exists()
    assert "Your order is being processed" in content
    assert "confirmation email at test@test.com shortly" in content


@pytest.mark.parametrize("url", ["/", "/?session_id=unknown-session"])
def test_success_view_no_session(rf, requests_mock, url):
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/unknown-session",
        status_code=404,
        json={"error": {"message": "No such checkout.session"}},
    )
    request = rf.get(url)
    resp = PayByStripe.success_view(request)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Your order is being processed" in content
    assert "You have been charged" not in content


def test_success_view_fulfil_error(rf, requests_mock, basket, caplog):
    # An error fulfilling the order from the success page is logged and left
    # for the webhook to handle
    basket = basket_from_checkout(basket)
    basket.save()
    requests_mock.get(
        "https://api.stripe.com/v1/checkout/sessions/test-session",
        json=stripe_session_data(client_reference_id=f"basket_{basket.id}"),
    )
    request = rf.get("/?session_id=test-session")
    request.user = AnonymousUser()
    with patch.object(
        Order.objects, "create_from_basket", side_effect=Exception("Error")
    ):
        resp = PayByStripe.success_view(request)

    assert resp.status_code == 200
    assert "Your order is being processed" in resp.content.decode()
    assert "Error fulfilling Stripe session test-session" in caplog.text
    # nothing was changed, so the webhook can still fulfil the order
    assert not Order.objects.exists()
    assert Basket.objects.filter(id=basket.id).exists()


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




@pytest.fixture
def get_mock_stripe_session():
    def stripe_session(**params):
        defaults = {
            "id": "session-id",
            "payment_intent": "payment-intent-id",
            "payment_status": "paid",
        }
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


def post_webhook(client):
    headers = {"STRIPE_SIGNATURE": f"v1=dummy,t={int(datetime.now(UTC).timestamp())}"}
    return client.post(reverse("shop-stripe-webhook"), data={}, headers=headers)


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed_duplicate_event(
    mock_webhook, client, basket, get_mock_webhook_event
):
    basket = basket_from_checkout(basket)
    basket.save()
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id=f"basket_{basket.id}",
        amount_total=basket.total * 100,
    )
    resp = post_webhook(client)
    assert resp.content.decode() == "Order fulfilled"

    # Stripe sends the same event again
    resp = post_webhook(client)
    assert resp.status_code == 200
    assert resp.content.decode() == "Order already fulfilled"
    assert Order.objects.count() == 1
    assert OrderPayment.objects.count() == 1


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed_missing_basket(
    mock_webhook, client, get_mock_webhook_event, caplog
):
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id="basket_1234", amount_total=1000
    )
    resp = post_webhook(client)
    # 200, so Stripe doesn't keep retrying
    assert resp.status_code == 200
    assert resp.content.decode() == "Missing basket"
    assert not Order.objects.exists()
    assert "Stripe payment payment-intent-id received for missing basket 1234" in caplog.text


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed_invalid_reference(
    mock_webhook, client, get_mock_webhook_event, caplog
):
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id="unknown", amount_total=1000, id="session-id"
    )
    resp = post_webhook(client)
    assert resp.status_code == 200
    assert resp.content.decode() == "Invalid session reference"
    assert "Invalid Stripe session reference: session-id" in caplog.text


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed_empty_basket(
    mock_webhook, client, basket, get_mock_webhook_event, caplog
):
    # Payment completed after the basket's items expired
    basket = basket_from_checkout(basket)
    basket.save()
    basket.clear()
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id=f"basket_{basket.id}", amount_total=2000
    )
    resp = post_webhook(client)
    assert resp.status_code == 200
    assert resp.content.decode() == "Order fulfilled"

    # Order and payment are recorded, and the order is flagged
    order = Order.objects.get()
    assert order.amount_paid == 20
    notes = list(order.notes.values_list("message", flat=True))
    assert len(notes) == 2
    assert "basket was empty" in notes[0]
    assert "doesn't match the order total" in notes[1]
    assert "basket was empty" in caplog.text


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed_amount_mismatch(
    mock_webhook, client, basket, get_mock_webhook_event
):
    basket = basket_from_checkout(basket)
    basket.save()
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id=f"basket_{basket.id}", amount_total=1500
    )
    resp = post_webhook(client)
    assert resp.content.decode() == "Order fulfilled"

    order = Order.objects.get()
    assert order.amount_paid == 15
    assert [note.message for note in order.notes.all()] == [
        "Payment payment-intent-id of £15.00 doesn't match the order total of £20.00."
    ]
    assert not order.notes.first().public


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed_existing_order(
    mock_webhook, client, order, get_mock_webhook_event
):
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id=f"order_{order.id}", amount_total=order.total * 100
    )
    resp = post_webhook(client)
    assert resp.content.decode() == "Order fulfilled"
    resp = post_webhook(client)
    assert resp.content.decode() == "Order already fulfilled"
    assert order.payments.count() == 1
    assert not order.notes.exists()


@patch("salesman_stripe.payment.stripe.Webhook")
def test_webhook_completed_missing_order(mock_webhook, client, get_mock_webhook_event):
    mock_webhook.construct_event.return_value = get_mock_webhook_event(
        client_reference_id="order_1234", amount_total=1000
    )
    resp = post_webhook(client)
    assert resp.status_code == 200
    assert resp.content.decode() == "Missing order"


def test_stripe_session_expiry_follows_basket_timeout(
    rf, mock_stripe, basket, freezer, settings
):
    settings.BASKET_TIMEOUT_MINUTES = 45
    freezer.move_to("2024-01-01 10:00")
    basket = basket_from_checkout(basket)
    session_data = PayByStripe().get_stripe_session_data(basket, rf.post("/"))
    assert session_data["expires_at"] == int(
        datetime(2024, 1, 1, 10, 46, tzinfo=UTC).timestamp()
    )
