"""
Browser tests of the site (outside the shop): see shop/tests/e2e/conftest.py
for how they run
"""

import os
import re
from datetime import timedelta

import pytest
import wagtail_factories
from django.utils import timezone
from model_bakery import baker
from wagtail.models import Site

from dogs.models import DogPage, DogsIndexPage, DogStatusPage
from fundraising.models import Auction, AuctionCategory, AuctionItem, AuctionsPage
from home.models import (
    FAQ,
    AdventCalendarDay,
    AdventCalendarPage,
    FAQPage,
    FormField,
    FormPage,
    NewsItemPage,
    NewsPage,
    StandardPage,
)
from shop.tests.factories import ShopPageFactory

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

E2E = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]

PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1280, "height": 900}}


@pytest.fixture
def browser_context_args(browser_context_args, request):
    return {**browser_context_args, **(getattr(request, "param", None) or DESKTOP)}


@pytest.fixture(autouse=True)
def no_icon_kit(page):
    # (the Font Awesome kit only adds icons, and calls home)
    page.route(re.compile(r"https://kit\.fontawesome\.com/.*"), lambda route: route.abort())
    page.set_default_timeout(10_000)
    return page


def add(parent, page):
    return parent.add_child(instance=page)


@pytest.fixture
def site_pages(home_page):
    """One page of each type (with some content and images), in the menus"""
    Site.objects.update(root_page=home_page, is_default_site=True)
    image = wagtail_factories.ImageFactory(title="Podenco running on a beach")
    body = "<p>Some text with <a href=\"/\">a link</a>.</p>"
    pages = {"home": home_page}
    pages["standard"] = add(home_page, StandardPage(title="About us", body=body, image=image, show_in_menus=True))
    faq = FAQPage(title="FAQs", introduction=body, show_in_menus=True)
    faq.faqs.add(FAQ(question="How do I adopt?", answer=body))
    pages["faq"] = add(home_page, faq)
    pages["news"] = add(home_page, NewsPage(title="News", body=body, show_in_menus=True))
    pages["news item"] = add(pages["news"], NewsItemPage(title="A news item", body=body, image=image))
    advent = AdventCalendarPage(title="Advent calendar", body=body)
    advent.days.add(AdventCalendarDay(image=image, caption="Day 1"))
    pages["advent"] = add(home_page, advent)
    contact = add(home_page, FormPage(title="Contact us", to_address="a@test.com", subject="Contact", show_in_menus=True))
    baker.make(FormField, label="Your email", field_type="email", page=contact)
    baker.make(FormField, label="Message", field_type="multiline", page=contact)
    pages["form"] = contact
    pages["dogs index"] = add(home_page, DogsIndexPage(title="Dogs", body=body, image=image, show_in_menus=True))
    pages["dog status"] = add(
        pages["dogs index"], DogStatusPage(
            title="Dogs for adoption", short_description="Ready for homes", image=image, show_in_menus=True
        )
    )
    pages["dog"] = add(pages["dog status"], DogPage(title="Rex", description=body, location="Spain"))
    pages["auctions"] = add(home_page, AuctionsPage(title="Auctions", body=body, show_in_menus=True))
    now = timezone.now()
    pages["auction"] = add(
        pages["auctions"], Auction(title="Winter auction", body=body, open_at=now - timedelta(days=1), close_at=now + timedelta(days=1))
    )
    pages["auction item"] = add(
        pages["auction"],
        AuctionItem(
            title="A painting", category=AuctionCategory.objects.create(name="Art"), description=body,
            donor="Ann", donor_email="ann@test.com", starting_bid=10,
        ),
    )
    pages["shop"] = ShopPageFactory(parent=home_page, title="Shop", slug="shop")
    return pages
