"""The shop's FAQs page"""

import pytest
from django.urls import reverse
from wagtail.models import Site

from ..models import ShopFAQ
from .factories import ShopPageFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop_page(home_page):
    # (the shop, at /shop/)
    Site.objects.filter(is_default_site=True).update(root_page=home_page)
    yield ShopPageFactory(parent=home_page, title="Shop", slug="shop")


def test_faqs_page(client, shop_page):
    resp = client.get(reverse("shop:faqs"))
    assert resp.status_code == 200
    # the FAQs from the migrations, in order
    assert [faq.question for faq in resp.context["faqs"]] == [
        "How much is delivery?",
        "Can I collect my order instead?",
        "Do you deliver outside the UK?",
        "When will my order arrive?",
        "Why has only part of my order arrived?",
    ]
    content = resp.content.decode()
    assert "<h2 class=\"shop-faq__question\">When will my order arrive?</h2>" in content
    assert "run by volunteers" in content
    # breadcrumbs: Home > Shop > FAQs
    assert [item["label"] for item in resp.context["items"]] == ["Home", "Shop", "FAQs"]


def test_faqs_page_no_faqs(client, shop_page):
    ShopFAQ.objects.all().delete()
    assert "No FAQs yet." in client.get(reverse("shop:faqs")).content.decode()


def test_new_faqs_go_last():
    faq = ShopFAQ.objects.create(question="Can I return something?", answer="<p>Yes.</p>")
    assert list(ShopFAQ.objects.all())[-1] == faq
    assert str(faq) == "Can I return something?"
    ShopFAQ.objects.all().delete()
    assert ShopFAQ.objects.create(question="First", answer="<p>-</p>").sort_order == 0


def test_faqs_linked_from_shop_page(client, shop_page):
    # (also from product pages, the basket and checkout: see their tests)
    content = client.get("/shop/").content.decode()
    assert f'<a href="{reverse("shop:faqs")}">Delivery and other FAQs</a>' in content
