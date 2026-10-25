"""
Browser (end-to-end) tests, with Playwright: the shop's main journeys, in a real
browser, so htmx and JavaScript are covered too. Run them separately from the
unit tests (they're marked e2e, and left out of the default run):

    pytest -m e2e -n 2

Each test has its own live server and database (transactional, with the data
from migrations restored, e.g. the shop's groups). Stripe isn't called: its API
is faked with requests_mock (the live server runs in the same process), so the
checkout goes straight to the success (or cancel) page, as if the customer had
paid (or cancelled) on Stripe's page.
"""

import os
import re
import urllib.parse
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from model_bakery import baker
from wagtail.models import Site

from ...models import DISPATCHERS_GROUP, Category, DiscountCode, Product, ProductVariant
from ..factories import ShopPageFactory

# Playwright's sync API runs an event loop, which Django would otherwise refuse
# to use the database in (the tests' fixtures and checks)
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

E2E = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]

PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1280, "height": 900}}

SESSIONS_URL = "https://api.stripe.com/v1/checkout/sessions"
SESSION_ID = "e2e-session"


@pytest.fixture
def browser_context_args(browser_context_args, request):
    # desktop, or e.g. @pytest.mark.parametrize("browser_context_args", [PHONE], indirect=True)
    return {**browser_context_args, **(getattr(request, "param", None) or DESKTOP)}


def choose_option(form, option):
    """Choose the variant whose option text includes option (e.g. "Black, S")"""
    value = form.locator("select[name=product_id] option", has_text=option).get_attribute("value")
    form.locator("select[name=product_id]").select_option(value)


@pytest.fixture(autouse=True)
def no_icon_kit(page):
    # (the Font Awesome kit only adds icons, and calls home)
    page.route(re.compile(r"https://kit\.fontawesome\.com/.*"), lambda route: route.abort())
    page.set_default_timeout(10_000)
    return page


@pytest.fixture
def dispatcher():
    user = baker.make("auth.User", username="ann", first_name="Ann", last_name="Smith", email="ann@test.com")
    user.groups.add(Group.objects.get(name=DISPATCHERS_GROUP))
    return user


@pytest.fixture
def shop(home_page, dispatcher):
    """
    The shop, at /shop/: a mug (sent by Ann, who's emailed), a T-shirt (sizes;
    Black M out of stock), cards (packs sharing stock), and a raffle ticket (no
    shipping, no stock limit); and discount codes TEST5 (£5) and FREE100 (£100)
    """
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    page = ShopPageFactory(parent=home_page, title="Shop", slug="shop")
    gifts = Category.objects.create(title="Mugs & Gifts")
    clothing = Category.objects.create(title="Clothing")
    cards_category = Category.objects.create(title="Cards")
    mug = Product.objects.create(
        category=gifts, name="Podenco mug", price=Decimal("10"), description="<p>A big mug.</p>",
        dispatcher=dispatcher, notify_dispatcher=True,
    )
    ProductVariant.objects.create(product=mug, stock=5)
    tshirt = Product.objects.create(category=clothing, name="PINS T-shirt", price=Decimal("18"))
    for sort_order, (colour, size, stock) in enumerate([("Black", "S", 2), ("Black", "M", 0), ("White", "M", 5)]):
        ProductVariant.objects.create(product=tshirt, colour=colour, size=size, stock=stock, sort_order=sort_order)
    cards = Product.objects.create(
        category=cards_category, name="Christmas cards", price=Decimal("3"), shares_stock=True, stock=12
    )
    ProductVariant.objects.create(product=cards, variant_name="Single", pack_size=1, sort_order=0)
    ProductVariant.objects.create(product=cards, variant_name="Pack of 5", pack_size=5, price=Decimal("12"), sort_order=1)
    raffle = Product.objects.create(
        category=gifts, name="Raffle ticket", price=Decimal("2"), requires_shipping=False, unlimited_stock=True
    )
    ProductVariant.objects.create(product=raffle)
    DiscountCode.objects.create(code="TEST5", amount=Decimal("5"))
    DiscountCode.objects.create(code="FREE100", amount=Decimal("100"))
    return {"page": page, "mug": mug, "tshirt": tshirt, "cards": cards, "raffle": raffle}


@pytest.fixture
def stripe(requests_mock, live_server):
    """
    Stripe's API, faked: creating a checkout session returns one whose page is
    the success page (as if the customer paid on Stripe's page; or set
    stripe["cancel"] = True to cancel instead), and the session is paid, for
    the basket that started it
    """
    state = {"cancel": False, "reference": None}

    def session(**params):
        return {
            "id": SESSION_ID,
            "object": "checkout.session",
            "client_reference_id": state["reference"],
            "customer_details": {"email": state.get("email", "")},
            "amount_total": state.get("amount", 0),
            "status": "complete",
            "payment_status": "paid",
            "payment_intent": "pi_e2e",
            "expires_at": 4102444800,
            **params,
        }

    def create(request, context):
        data = urllib.parse.parse_qs(request.text)
        state["reference"] = data["client_reference_id"][0]
        state["email"] = data.get("customer_email", [""])[0]
        state["amount"] = sum(
            int(data[key][0]) * int(data[key.replace("[price_data][unit_amount]", "[quantity]")][0])
            for key in data
            if key.endswith("[price_data][unit_amount]")
        )
        if state["cancel"]:
            url = live_server.url + reverse("stripe-connect-cancel")
        else:
            url = f"{live_server.url}{reverse('stripe-connect-success')}?session_id={SESSION_ID}"
        return session(url=url, status="open", payment_status="unpaid")

    requests_mock.post(SESSIONS_URL, json=create)
    requests_mock.get(f"{SESSIONS_URL}/{SESSION_ID}", json=lambda request, context: session())
    requests_mock.post(
        f"{SESSIONS_URL}/{SESSION_ID}/expire",
        json=lambda request, context: session(status="expired", payment_status="unpaid"),
    )
    return state


def log_in(page, live_server, user):
    """Log the browser in as the user (with a session made by Django's test client)"""
    client = Client()
    client.force_login(user)
    page.context.add_cookies(
        [{"name": "sessionid", "value": client.cookies["sessionid"].value, "url": live_server.url}]
    )


@pytest.fixture
def admin_user():
    return baker.make("auth.User", username="admin", is_superuser=True, is_staff=True, first_name="Ada")


def user_in(group, **kwargs):
    user = baker.make("auth.User", **kwargs)
    user.groups.add(Group.objects.get(name=group))
    return user


# Shopping


def card(page, name):
    return page.locator("article.shop-card", has_text=name)


def add_to_basket(page, live_server, product, quantity=1, option=None):
    """Add the product to the basket from its page (choosing the option, e.g. "Black, S")"""
    page.goto(f"{live_server.url}{reverse('shop:product_detail', args=(product.pk,))}")
    form = page.locator(".shop-product")
    if option:
        choose_option(form, option)
    for _ in range(quantity - 1):
        form.get_by_role("button", name="More").click()
        page.wait_for_timeout(150)
    form.get_by_role("button", name="Add to basket").click()
    form.get_by_text("Added!").wait_for()


def field(page, label):
    """
    A form field by its label (crispy forms adds "*" to required fields' labels;
    a regular expression is matched against the label's text with its spaces)
    """
    return page.get_by_label(re.compile(rf"^\s*{re.escape(label)}\*?\s*$"))


def fill_checkout(page, delivery=True, **values):
    """Fill in the checkout form (with a UK delivery address)"""
    fields = {
        "Name": "Cat Customer",
        "Email": "cat@test.com",
        "Email (again)": "cat@test.com",
        "Mobile number": "07700 900123",
        **({"Address line 1": "1 Road", "Town or city": "Town", "Postcode": "sw1a1aa", "Safe place": "Porch"} if delivery else {}),
        **values,
    }
    for label, value in fields.items():
        field(page, label).fill(value)
    page.get_by_label(re.compile("Data Privacy Policy")).check()
