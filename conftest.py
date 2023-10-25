from wagtail.models import Site

import pytest

import wagtail_factories


pytestmark = pytest.mark.django_db


class HomePageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = "home.HomePage"


@pytest.fixture(autouse=True)
def root_page():
    page = wagtail_factories.PageFactory(parent=None)
    Site.objects.create(
        hostname='localhost',
        port=8000,
        root_page=page
    )
    yield page


@pytest.fixture
def home_page(root_page):
    yield HomePageFactory(
        parent=root_page, title="Home", hero_text="Home", hero_cta="Test", body="Test"
    )
