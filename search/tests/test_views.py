"""The site search ("Search for dogs"): dog pages only"""

import pytest
from django.urls import reverse
from wagtail.models import Site

from dogs.tests.test_models import DogPageFactory, DogsIndexPageFactory, DogStatusPageFactory
from home.models import StandardPage

pytestmark = pytest.mark.django_db


@pytest.fixture
def pages(home_page):
    Site.objects.update(root_page=home_page, is_default_site=True)
    index = DogsIndexPageFactory(parent=home_page, title="Dogs")
    status = DogStatusPageFactory(parent=index, title="Dogs for adoption", live=True)
    rex = DogPageFactory(parent=status, title="Rex")
    DogPageFactory(parent=status, title="Rexina", live=False)
    # e.g. the hidden shop preview: not found
    other = home_page.add_child(instance=StandardPage(title="Rex's shop preview"))
    return {"rex": rex, "other": other}


def results(client, query):
    resp = client.get(reverse("search"), {"q": query})
    return [page.title for page in resp.context["search_results"]]


def test_finds_live_dog_pages_only(client, pages):
    # not other pages, or draft dogs
    assert results(client, "rex") == ["Rex"]


def test_no_query(client, pages):
    resp = client.get(reverse("search"))
    assert list(resp.context["search_results"]) == []
    assert "You didn&apos;t search for anything!" in resp.content.decode()


@pytest.mark.parametrize("page", ["2", "x"])
def test_pages(client, pages, page):
    # (past the last page, or not a number: a page of results)
    resp = client.get(reverse("search"), {"q": "rex", "page": page})
    assert [p.title for p in resp.context["search_results"]] == ["Rex"]
