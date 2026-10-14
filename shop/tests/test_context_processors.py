import pytest
from model_bakery import baker

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.urls import reverse
from wagtail.models import Site

from salesman.basket.models import BASKET_ID_SESSION_KEY
from salesman.core.utils import get_salesman_model

from ..context_processors import shop_context
from .factories import ShopPageFactory

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")


@pytest.fixture
def site_home_page(home_page):
    # Serve the home page from the default site, so pages can be requested
    # with the test client
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    yield home_page


@pytest.fixture
def anon_request(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    request.session = SessionStore()
    return request


def test_shop_context_no_basket(anon_request):
    context = shop_context(anon_request)
    assert context["basket_quantity"] == 0
    assert not Basket.objects.exists()
    assert BASKET_ID_SESSION_KEY not in anon_request.session


def test_shop_context_session_basket(anon_request, basket):
    anon_request.session[BASKET_ID_SESSION_KEY] = basket.id
    context = shop_context(anon_request)
    assert context["basket_quantity"] == 2


def test_shop_context_session_basket_deleted(anon_request):
    anon_request.session[BASKET_ID_SESSION_KEY] = 1234
    context = shop_context(anon_request)
    assert context["basket_quantity"] == 0
    assert not Basket.objects.exists()


def test_shop_context_user_basket(rf, basket):
    user = baker.make("auth.User")
    basket.user = user
    basket.save()
    request = rf.get("/")
    request.user = user
    request.session = SessionStore()
    context = shop_context(request)
    assert context["basket_quantity"] == 2


def test_shop_context_is_lazy(anon_request, django_assert_num_queries, basket):
    anon_request.session[BASKET_ID_SESSION_KEY] = basket.id
    with django_assert_num_queries(0):
        shop_context(anon_request)


def test_non_shop_page_does_not_create_basket(client, site_home_page):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.context["page"] == site_home_page
    assert not Basket.objects.exists()


def test_shop_page_does_not_create_basket(client, site_home_page):
    shop_page = ShopPageFactory(parent=site_home_page, title="Shop", slug="shop")
    resp = client.get("/shop/")
    assert resp.status_code == 200
    assert resp.context["page"] == shop_page
    assert not Basket.objects.exists()
    assert "(0)" in resp.content.decode()


def test_logged_out_visitor_can_shop(client, site_home_page, product):
    # Browsing doesn't create a basket, but adding to the basket does, and
    # the basket count is then shown on shop pages
    ShopPageFactory(parent=site_home_page, title="Shop", slug="shop")
    variant = baker.make("shop.ProductVariant", product=product, price=10, stock=5)

    client.get("/shop/")
    assert not Basket.objects.exists()

    resp = client.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "product_id": variant.id,
            "product_type": "shop.ProductVariant",
            "quantity": 2,
        },
    )
    assert resp.status_code == 200
    assert Basket.objects.count() == 1
    basket = Basket.objects.get()
    assert basket.user is None
    assert basket.quantity == 2
    assert client.session[BASKET_ID_SESSION_KEY] == basket.id

    resp = client.get("/shop/")
    assert resp.context["basket_quantity"] == 2
    assert "(2)" in resp.content.decode()
    assert Basket.objects.count() == 1


def test_shop_context_merges_session_basket_on_login(rf, basket):
    # The user has an empty basket from a previous visit, and a session basket
    # with items added before they logged in
    user = baker.make("auth.User")
    user_basket = baker.make("shop.Basket", user=user)
    request = rf.get("/")
    request.user = user
    request.session = SessionStore()
    request.session[BASKET_ID_SESSION_KEY] = basket.id

    context = shop_context(request)
    assert context["basket_quantity"] == 2
    # the session basket has been merged into the user basket
    assert not Basket.objects.filter(id=basket.id).exists()
    assert Basket.objects.get(id=user_basket.id).quantity == 2
    assert BASKET_ID_SESSION_KEY not in request.session


def test_shop_context_logged_in_without_session_basket(rf):
    # A logged in user who hasn't added anything doesn't get a basket created
    user = baker.make("auth.User")
    request = rf.get("/")
    request.user = user
    request.session = SessionStore()
    context = shop_context(request)
    assert context["basket_quantity"] == 0
    assert not Basket.objects.exists()


def test_visitor_logs_in_after_adding_to_basket(client, site_home_page, product):
    ShopPageFactory(parent=site_home_page, title="Shop", slug="shop")
    variant = baker.make("shop.ProductVariant", product=product, price=10, stock=5)
    user = baker.make("auth.User")
    baker.make("shop.Basket", user=user)

    client.post(
        reverse("shop:add_to_basket", args=(product.id,)),
        {
            "product_id": variant.id,
            "product_type": "shop.ProductVariant",
            "quantity": 2,
        },
    )
    client.force_login(user)

    resp = client.get("/shop/")
    assert resp.context["basket_quantity"] == 2
    assert "(2)" in resp.content.decode()
    assert Basket.objects.get().user == user
    assert BASKET_ID_SESSION_KEY not in client.session
    # stock is unaffected by the merge
    variant.refresh_from_db()
    assert variant.stock == 3
