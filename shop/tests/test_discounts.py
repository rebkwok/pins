"""
Discount codes: a single-use amount off the whole basket (including shipping,
after sale prices), claimed when payment starts and used by the order.
"""
import html
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker
from salesman.checkout.payment import PaymentError
from salesman.core.utils import get_salesman_model

from ..models import (
    DISCOUNT_CODE_CHARACTERS,
    DISCOUNT_CODE_IN_USE,
    DISCOUNT_CODE_INVALID,
    DISCOUNT_CODE_TOO_LITTLE_LEFT,
    DISCOUNT_CODE_USED,
    DiscountCode,
)
from ..payment import PayByStripe

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")

SESSIONS_URL = "https://api.stripe.com/v1/checkout/sessions"
SESSION_URL = f"{SESSIONS_URL}/test-session"


@pytest.fixture
def code():
    return DiscountCode.objects.create(code="pins5off", amount=Decimal("5.00"))


@pytest.fixture
def discounted_basket(basket, code):
    # basket: 2 x £10, collected (no shipping)
    basket.set_discount_code(code)
    basket.update(request=None)
    return basket


def checkout_ready(basket):
    basket.extra.update(
        {
            "email": "test@test.com",
            "shipping_address": "-",
            "consent": "on",
            "billing_address": "-",
            "payment_method": "stripe",
        }
    )
    basket.save()
    return basket


# The model


def test_code_case_insensitive(code):
    assert code.code == "PINS5OFF"
    assert str(code) == "PINS5OFF"
    assert DiscountCode.find(" pins5Off ") == code
    assert DiscountCode.find("other") is None
    assert DiscountCode.find("") is None


def test_generated_code():
    code = DiscountCode.objects.create(amount=5)
    assert len(code.code) == 8
    assert set(code.code) <= set(DISCOUNT_CODE_CHARACTERS)
    # clean() generates one too, so the admin form can check it's unique
    code = DiscountCode(amount=5)
    code.clean()
    assert len(code.code) == 8


def test_generated_code_unique(monkeypatch):
    DiscountCode.objects.create(code="AAAAAAAA", amount=5)
    choices = iter("A" * 8 + "B" * 8)
    monkeypatch.setattr("shop.models.secrets.choice", lambda chars: next(choices))
    assert DiscountCode.generate_code() == "BBBBBBBB"


def test_unavailable_reason(code, basket):
    other = baker.make(Basket)
    assert code.unavailable_reason(basket) is None
    # claimed by another basket's payment
    code.basket = other
    other.start_payment("cs_1", "https://stripe", hold_until=None)
    assert code.unavailable_reason(basket) == DISCOUNT_CODE_IN_USE
    assert code.status() == "Payment in progress"
    # a claim by a basket whose payment has ended doesn't count
    other.extra.pop(other.STRIPE_SESSION_KEY)
    assert code.unavailable_reason(basket) is None
    # claimed by this basket: still usable, even if disabled since
    code.basket = basket
    code.active = False
    assert code.unavailable_reason(basket) is None
    code.basket = None
    assert code.unavailable_reason(basket) == DISCOUNT_CODE_INVALID
    assert code.status() == "Disabled"
    code.order = baker.make(Order)
    assert code.unavailable_reason(basket) == DISCOUNT_CODE_USED
    assert code.status() == f"Used (order {code.order})"


def test_status_available(code):
    assert code.status() == "Available"


# The discount


def test_discount_row(discounted_basket):
    assert discounted_basket.total == 15
    row = discounted_basket.extra_rows["discount-code"].data
    assert row == {"label": "Discount code PINS5OFF", "amount": "-5.00", "extra": {"code": "PINS5OFF"}}
    assert discounted_basket.discount_problem is None
    assert discounted_basket.discount_unused == 0


def test_discount_includes_shipping(discounted_basket, code):
    # £20 + £4.99 shipping, less £24.99
    discounted_basket.shipping_method = "deliver"
    code.amount = Decimal("24.99")
    code.save()
    discounted_basket.update(request=None)
    assert discounted_basket.total == 0
    assert discounted_basket.discount_unused == 0


def test_discount_after_sale_prices(discounted_basket, sale_with_items, freezer):
    # 2 x £10 with 20% off is £16, less £5
    freezer.move_to(datetime(2022, 1, 1, 9, tzinfo=UTC))
    discounted_basket.update(request=None)
    assert discounted_basket.total == 11


def test_discount_covers_basket(discounted_basket, code):
    code.amount = 50
    code.save()
    discounted_basket.update(request=None)
    assert discounted_basket.total == 0
    assert discounted_basket.extra_rows["discount-code"].data["amount"] == "-20.00"
    assert discounted_basket.discount_unused == 30


@pytest.mark.parametrize(
    "amount,applied", [("19.71", False), ("19.99", False), ("19.70", True), ("20.00", True)]
)
def test_discount_too_little_left(discounted_basket, code, amount, applied):
    # less than 30p (but more than nothing) left to pay can't be paid by card
    code.amount = Decimal(amount)
    code.save()
    discounted_basket.update(request=None)
    assert ("discount-code" in discounted_basket.extra_rows) == applied
    assert discounted_basket.discount_problem == (
        None if applied else DISCOUNT_CODE_TOO_LITTLE_LEFT
    )


def test_discount_unavailable_code(discounted_basket, code):
    code.active = False
    code.save()
    discounted_basket.update(request=None)
    assert discounted_basket.total == 20
    assert discounted_basket.discount_problem == DISCOUNT_CODE_INVALID


def test_discount_deleted_code(discounted_basket, code):
    code.delete()
    discounted_basket.update(request=None)
    assert discounted_basket.total == 20
    assert discounted_basket.discount_problem == DISCOUNT_CODE_INVALID


def test_no_discount_empty_basket(discounted_basket):
    discounted_basket.clear()
    discounted_basket.update(request=None)
    assert discounted_basket.extra_rows == {}
    assert discounted_basket.discount_problem is None


# The basket page


@pytest.fixture
def basket_client(client, basket):
    session = client.session
    session["BASKET_ID"] = basket.id
    session.save()
    return client


def messages_for(resp):
    return [str(m) for m in get_messages(resp.wsgi_request)]


def apply(client, code):
    return client.post(reverse("shop:apply_discount_code"), {"code": code})


def test_basket_page_discount_form(basket_client):
    content = basket_client.get(reverse("shop:basket")).content.decode()
    assert 'name="code"' in content
    assert reverse("shop:apply_discount_code") in content


def test_apply_code(basket_client, basket, code):
    resp = apply(basket_client, "pins5off")
    assert resp.url == reverse("shop:basket")
    assert messages_for(resp) == ["Discount code PINS5OFF applied."]
    basket.refresh_from_db()
    assert basket.discount_code == code
    content = html.unescape(basket_client.get(reverse("shop:basket")).content.decode())
    assert "Discount code PINS5OFF" in content
    assert "-£5.00" in content
    # the basket's shipping method (collection) is kept: £20, less £5
    assert 'id="total">15.00<' in content
    assert 'id="id_collect" value="collect" checked' in " ".join(content.split())
    # the code is shown once, on its row in the totals, with a Remove button
    assert content.count(f'action="{reverse("shop:remove_discount_code")}"') == 1
    assert "Discount code <strong>PINS5OFF</strong>" not in content
    assert 'name="code"' not in content


def test_apply_code_free_keeps_collection(basket_client, basket, code):
    # a code covering the order, with collection chosen: still collection
    code.amount = 25
    code.save()
    basket.shipping_method = "collect"
    basket.save()
    apply(basket_client, "pins5off")
    content = html.unescape(basket_client.get(reverse("shop:basket")).content.decode())
    assert 'id="total">0.00<' in content
    assert 'id="id_collect" value="collect" checked' in " ".join(content.split())
    basket.refresh_from_db()
    assert basket.shipping_method == "collect"


@pytest.mark.parametrize(
    "setup,message",
    [
        ({"active": False}, DISCOUNT_CODE_INVALID),
        ({"order": True}, DISCOUNT_CODE_USED),
        ({"amount": Decimal("19.80")}, DISCOUNT_CODE_TOO_LITTLE_LEFT),
    ],
)
def test_apply_code_refused(basket_client, basket, code, setup, message):
    if setup.pop("order", None):
        setup["order"] = baker.make(Order)
    DiscountCode.objects.filter(id=code.id).update(**setup)
    resp = apply(basket_client, "PINS5OFF")
    assert messages_for(resp) == [message]
    basket.refresh_from_db()
    assert basket.discount_code is None


def test_apply_unknown_code(basket_client, basket):
    assert messages_for(apply(basket_client, "nope")) == [DISCOUNT_CODE_INVALID]


def test_apply_code_in_use(basket_client, basket, code):
    other = baker.make(Basket)
    other.start_payment("cs_1", "https://stripe", hold_until=None)
    DiscountCode.objects.filter(id=code.id).update(basket=other)
    assert messages_for(apply(basket_client, "PINS5OFF")) == [DISCOUNT_CODE_IN_USE]


def test_apply_code_empty_basket(client, code):
    resp = apply(client, "PINS5OFF")
    assert messages_for(resp) == ["Your basket is empty."]


def test_apply_and_remove_code_payment_in_progress(basket_client, basket, code):
    basket.start_payment("cs_1", "https://stripe", hold_until=None)
    resp = apply(basket_client, "PINS5OFF")
    assert "can't be changed while a payment is in progress" in messages_for(resp)[0]
    resp = basket_client.post(reverse("shop:remove_discount_code"))
    assert "can't be changed while a payment is in progress" in messages_for(resp)[0]


def test_remove_code(basket_client, discounted_basket):
    resp = basket_client.post(reverse("shop:remove_discount_code"))
    assert resp.url == reverse("shop:basket")
    assert messages_for(resp) == ["Discount code removed."]
    discounted_basket.refresh_from_db()
    assert discounted_basket.discount_code is None


def test_remove_code_no_basket(client):
    resp = client.post(reverse("shop:remove_discount_code"))
    assert resp.url == reverse("shop:basket")
    assert messages_for(resp) == []


def test_basket_page_code_covers_basket(basket_client, discounted_basket, code):
    # £20 + £4.99 shipping
    discounted_basket.shipping_method = "deliver"
    discounted_basket.save()
    code.amount = Decimal("30.00")
    code.save()
    content = html.unescape(basket_client.get(reverse("shop:basket")).content.decode())
    assert "Your discount code covers the whole order, so there's nothing to pay." in content
    assert "The £5.01 left on the code can't be refunded or used again." in content


def test_basket_page_code_problem(basket_client, discounted_basket, code):
    # e.g. the basket has changed since the code was applied: £24.99 (with
    # shipping) less £24.80 leaves 19p
    discounted_basket.shipping_method = "deliver"
    discounted_basket.save()
    code.amount = Decimal("24.80")
    code.save()
    content = html.unescape(basket_client.get(reverse("shop:basket")).content.decode())
    # (styled as the other discount messages)
    assert (
        '<p class="basket-discount__message basket-discount__message--error mb-0">'
        "Discount cannot be applied to this basket.</p>"
    ) in content
    assert 'id="total">24.99<' in content
    # it isn't in the totals, so it's shown (with its Remove button) with the reason
    assert "Discount code <strong>PINS5OFF</strong>" in content
    assert content.count(f'action="{reverse("shop:remove_discount_code")}"') == 1


def test_htmx_updates_include_discount(basket_client, discounted_basket):
    # changing the quantity can change whether the code applies
    item = discounted_basket.items.get()
    resp = basket_client.post(
        reverse("shop:update_quantity", args=(item.ref,)),
        {"variant_id": item.product_id, "quantity": 1},
    )
    content = resp.content.decode()
    assert '<div id="basket-discount" class="basket-discount" hx-swap-oob="true">' in content
    assert "<span id='total' hx-swap-oob='true'>5.00</span>" in content
    resp = basket_client.post(
        reverse("shop:update_shipping_method"), {"shipping-method": "deliver"}
    )
    assert 'id="basket-discount"' in resp.content.decode()


def test_htmx_delete_includes_discount(basket_client, discounted_basket, product):
    variant = baker.make("shop.ProductVariant", product=product, variant_name="Large", price=1, stock=5)
    discounted_basket.add(variant)
    item = discounted_basket.items.get(product_id=variant.id)
    resp = basket_client.post(
        reverse("shop:delete_basket_item", args=(item.ref,)), {"variant_id": variant.id}
    )
    assert 'id="basket-discount"' in resp.content.decode()


# Checkout


def checkout_url():
    return reverse("shop:checkout") + "?payment-method=stripe&shipping-method=collect"


def test_checkout_page_discount(basket_client, discounted_basket):
    content = html.unescape(basket_client.get(checkout_url()).content.decode())
    assert "Discount code PINS5OFF" in content
    assert "-£5.00" in content
    assert 'value="Pay Now"' in content
    assert "Clicking Pay Now takes you to Stripe to complete your payment." in content
    # it's removed on the basket page
    assert reverse("shop:remove_discount_code") not in content


def test_checkout_page_free(basket_client, discounted_basket, code):
    code.amount = 25
    code.save()
    content = html.unescape(basket_client.get(checkout_url()).content.decode())
    assert "Your discount code covers the whole order, so there's nothing to pay." in content
    assert 'value="Place order"' in content
    # nothing to pay, so not to Stripe
    assert "Clicking Pay Now takes you to Stripe to complete your payment." not in content


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(
    "setup,message",
    [
        ({"active": False}, f"Discount code PINS5OFF removed: {DISCOUNT_CODE_INVALID}"),
        ({"order": True}, f"Discount code PINS5OFF removed: {DISCOUNT_CODE_USED}"),
        # being paid for in another basket
        ({"basket": True}, f"Discount code PINS5OFF removed: {DISCOUNT_CODE_IN_USE}"),
    ],
)
def test_checkout_code_removed(basket_client, discounted_basket, code, method, setup, message):
    # the code isn't valid: removed, and back to the basket
    if setup.pop("order", None):
        setup["order"] = baker.make(Order)
    if setup.pop("basket", None):
        other = baker.make(Basket)
        other.start_payment("cs_2", "https://stripe", hold_until=None)
        setup["basket"] = other
    DiscountCode.objects.filter(id=code.id).update(**setup)
    orders = Order.objects.count()
    resp = getattr(basket_client, method)(checkout_url())
    assert resp.url == reverse("shop:basket")
    assert messages_for(resp) == [message]
    assert Basket.objects.get(id=discounted_basket.id).discount_code is None
    # no order is created
    assert Order.objects.count() == orders


def test_checkout_code_kept(basket_client, discounted_basket, code):
    # the code would leave too little to pay: kept (it applies if the basket
    # changes), and back to the basket, which says why by the code (so no
    # message as well)
    DiscountCode.objects.filter(id=code.id).update(amount=Decimal("19.80"))
    resp = basket_client.get(checkout_url())
    assert resp.url == reverse("shop:basket")
    assert messages_for(resp) == []
    assert Basket.objects.get(id=discounted_basket.id).discount_code == code


# Payment


def payment_request(rf):
    request = rf.post("/", {"name": "Test buyer"})
    request.user = AnonymousUser()
    return request


@pytest.fixture
def create_session(requests_mock):
    return requests_mock.post(
        SESSIONS_URL,
        json={
            "id": "test-session",
            "object": "checkout.session",
            "url": "https://stripe-session-url",
            "expires_at": 1704105060,
        },
    )


def test_payment_claims_code(rf, discounted_basket, code, create_session):
    checkout_ready(discounted_basket)
    url = PayByStripe().basket_payment(discounted_basket, payment_request(rf))
    assert url == "https://stripe-session-url"
    code.refresh_from_db()
    assert code.basket == discounted_basket
    assert code.status() == "Payment in progress"
    # the session is for the discounted total
    assert "[unit_amount]=1500" in create_session.last_request.text


def test_payment_code_problem(rf, discounted_basket, code, create_session):
    code.active = False
    code.save()
    with pytest.raises(PaymentError, match=DISCOUNT_CODE_INVALID):
        PayByStripe().basket_payment(checkout_ready(discounted_basket), payment_request(rf))
    assert not create_session.called


def test_payment_code_claimed_meanwhile(rf, discounted_basket, code, create_session, monkeypatch):
    # another basket's payment claims it after this basket was updated
    other = baker.make(Basket)
    other.start_payment("cs_2", "https://stripe", hold_until=None)

    original_update = Basket.update

    def update_then_claim(self, request):
        original_update(self, request)
        DiscountCode.objects.filter(id=code.id).update(basket=other)

    monkeypatch.setattr(Basket, "update", update_then_claim)
    with pytest.raises(PaymentError, match=DISCOUNT_CODE_IN_USE):
        PayByStripe().basket_payment(checkout_ready(discounted_basket), payment_request(rf))
    assert not create_session.called


def test_payment_error_releases_code(rf, discounted_basket, code, requests_mock):
    requests_mock.post(SESSIONS_URL, status_code=500, json={"error": {"message": "Down"}})
    with pytest.raises(PaymentError):
        PayByStripe().basket_payment(checkout_ready(discounted_basket), payment_request(rf))
    code.refresh_from_db()
    assert code.basket is None


@pytest.mark.parametrize("end", ["cancel", "expire", "clear_expired"])
def test_payment_ended_releases_code(rf, discounted_basket, code, create_session, requests_mock, freezer, end):
    freezer.move_to("2024-01-01 10:00")
    PayByStripe().basket_payment(checkout_ready(discounted_basket), payment_request(rf))
    if end == "cancel":
        requests_mock.post(f"{SESSION_URL}/expire", json={"id": "test-session", "status": "expired"})
        PayByStripe.cancel_basket_payment(discounted_basket)
    elif end == "expire":
        PayByStripe.expire_basket_payment(
            Mock(id="test-session", client_reference_id=f"basket_{discounted_basket.id}")
        )
    else:
        freezer.move_to("2024-01-01 11:00")
        assert Basket.clear_expired() == 1
    code.refresh_from_db()
    assert code.basket is None
    assert code.status() == "Available"
    # a cancelled payment: the basket keeps its items and the code; an expired
    # one (or timed out basket) is emptied, so it loses the code
    expected = code if end == "cancel" else None
    assert Basket.objects.get(id=discounted_basket.id).discount_code == expected


def test_order_uses_code(rf, discounted_basket, code, freezer):
    freezer.move_to("2024-01-01 10:00")
    DiscountCode.objects.filter(id=code.id).update(basket=discounted_basket)
    order = Order.objects.create_from_basket(discounted_basket, None)
    assert order.total == 15
    assert order.discount_code == "PINS5OFF"
    code.refresh_from_db()
    assert (code.order, code.basket) == (order, None)
    assert code.date_used == datetime(2024, 1, 1, 10, tzinfo=UTC)
    assert code.status() == f"Used (order {order})"


def test_order_without_code(order):
    assert order.discount_code is None


def test_free_order(rf, discounted_basket, code, requests_mock):
    # the code covers the basket: no card payment
    code.amount = 25
    code.save()
    variant = discounted_basket.items.get().product
    request = payment_request(rf)
    url = PayByStripe().basket_payment(checkout_ready(discounted_basket), request)
    assert not requests_mock.called
    order = Order.objects.get()
    assert url == request.build_absolute_uri(reverse("shop:new_order_status", args=(order.token,)))
    assert order.status == Order.Status.PROCESSING
    assert (order.total, order.is_paid) == (0, True)
    assert order.extra_rows[-1]["amount"] == "-20.00"
    assert [note.message for note in order.notes.all()] == [
        "Paid in full by discount code PINS5OFF."
    ]
    code.refresh_from_db()
    assert code.order == order
    assert not Basket.objects.filter(id=discounted_basket.id).exists()
    # the items stay out of stock
    variant.refresh_from_db()
    assert variant.stock == 3


def test_free_order_from_checkout(basket_client, discounted_basket, code):
    code.amount = 20
    code.save()
    data = {
        "email": "test@test.com",
        "email1": "test@test.com",
        "name": "Test",
        "payment_method": "stripe",
        "shipping_method": "collect",
        "billing_address": "-",
        "shipping_address": "-",
        "consent": "on",
    }
    resp = basket_client.post(checkout_url(), data)
    order = Order.objects.get()
    assert resp.url == f"http://testserver{reverse('shop:new_order_status', args=(order.token,))}"


# Admin


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    return client


def test_admin_list(admin_client, code):
    baker.make(DiscountCode, code="USED1", amount=2, order=baker.make(Order))
    content = admin_client.get(reverse("wagtailsnippets_shop_discountcode:list")).content.decode()
    assert "PINS5OFF" in content
    assert "Available" in content
    assert "Used (order" in content


def test_admin_create_generated_code(admin_client):
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_discountcode:add"),
        {"code": "", "amount": "5.00", "active": "on", "description": "Raffle prize"},
    )
    assert resp.status_code == 302
    code = DiscountCode.objects.get()
    assert len(code.code) == 8


def test_admin_create_duplicate_code(admin_client, code):
    resp = admin_client.post(
        reverse("wagtailsnippets_shop_discountcode:add"),
        {"code": "Pins5Off", "amount": "5.00", "active": "on"},
    )
    assert resp.status_code == 200
    assert "already exists" in html.unescape(resp.content.decode())
    assert DiscountCode.objects.count() == 1


# Applying and removing codes with htmx: the basket page's summary is replaced
# (keeping the page's scroll position), with the message under the code


def htmx_post(client, url, data=None):
    return client.post(url, data or {}, headers={"HX-Request": "true"})


def test_apply_code_htmx(basket_client, basket, code):
    resp = htmx_post(basket_client, reverse("shop:apply_discount_code"), {"code": "pins5off"})
    content = " ".join(html.unescape(resp.content.decode()).split())
    assert content.startswith('<aside id="basket-summary"')
    assert (
        '<p class="basket-discount__message basket-discount__message--success" role="status">'
        "Discount code PINS5OFF applied.</p>"
    ) in content
    # the totals include it, with its Remove button (also htmx)
    assert "-£5.00" in content
    assert 'id="total">15.00<' in content
    # (the message comes straight after the code's row in the totals)
    assert content.index("-£5.00") < content.index("Discount code PINS5OFF applied.")
    assert 'hx-post="/shop/basket/discount/remove/" hx-target="#basket-summary"' in content
    # (not as a message on the next page)
    assert messages_for(resp) == []


def test_apply_code_htmx_refused(basket_client, basket, code):
    resp = htmx_post(basket_client, reverse("shop:apply_discount_code"), {"code": "nope"})
    content = html.unescape(resp.content.decode())
    message = f'basket-discount__message--error mt-2" role="status">{DISCOUNT_CODE_INVALID}</p>'
    assert message in content
    # the field is still there, to try again, with the message under it
    assert 'name="code"' in content
    assert content.index('name="code"') < content.index(message)


def test_remove_code_htmx(basket_client, discounted_basket):
    resp = htmx_post(basket_client, reverse("shop:remove_discount_code"))
    content = html.unescape(resp.content.decode())
    assert 'role="status">Discount code removed.</p>' in content
    assert 'name="code"' in content
    discounted_basket.refresh_from_db()
    assert discounted_basket.discount_code is None


def test_discount_code_htmx_empty_basket(client, code):
    # nothing to update: the page is reloaded, with the message
    resp = htmx_post(client, reverse("shop:apply_discount_code"), {"code": "pins5off"})
    assert resp.headers["HX-Refresh"] == "true"
    assert messages_for(resp) == ["Your basket is empty."]


def test_remove_code_htmx_no_basket(client):
    resp = htmx_post(client, reverse("shop:remove_discount_code"))
    assert resp.headers["HX-Refresh"] == "true"
    assert messages_for(resp) == []


# An emptied basket loses its discount code, so it isn't still applied when the
# customer next shops


def test_removing_last_item_removes_code(basket_client, discounted_basket, product):
    other = baker.make("shop.ProductVariant", product=product, variant_name="Large", stock=5)
    discounted_basket.add(other)
    first, second = discounted_basket.get_items()
    # one item left: the code stays
    discounted_basket.remove(first.ref)
    assert Basket.objects.get(id=discounted_basket.id).discount_code is not None
    # the last one, from the basket page: it's removed
    basket_client.post(
        reverse("shop:delete_basket_item", args=(second.ref,)),
        {"variant_id": second.product.id},
    )
    basket = Basket.objects.get(id=discounted_basket.id)
    assert basket.discount_code is None
    assert Basket.DISCOUNT_CODE_KEY not in basket.extra


def test_expired_basket_loses_code(discounted_basket, product, freezer):
    freezer.move_to(timezone.now() + timedelta(days=1))
    assert Basket.clear_expired() == 1
    basket = Basket.objects.get(id=discounted_basket.id)
    assert not basket.items.exists()
    assert basket.discount_code is None
    # adding something later: no code
    variant = baker.make("shop.ProductVariant", product=product, stock=5, price=3)
    basket.add(variant)
    assert Basket.objects.get(id=basket.id).discount_code is None


def test_cleared_basket_loses_code(discounted_basket):
    # e.g. its checkout session expired
    discounted_basket.clear()
    assert Basket.objects.get(id=discounted_basket.id).discount_code is None


def test_clear_basket_without_code(basket):
    basket.clear()
    assert Basket.DISCOUNT_CODE_KEY not in Basket.objects.get(id=basket.id).extra
