from datetime import date
import wagtail_factories
import pytest

from dogs.models import DogsIndexPage, DogIndexPageStatuses, DogStatusPage, DogPage, FacebookAlbums


pytestmark = pytest.mark.django_db


class DogsIndexPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = DogsIndexPage


class DogStatusPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = DogStatusPage


class DogPageFactory(wagtail_factories.PageFactory):
    class Meta:
        model = DogPage


@pytest.fixture
def dog_index_page(root_page):
    yield DogsIndexPageFactory(parent=root_page)


@pytest.fixture
def dog_status_page(dog_index_page):
    yield DogStatusPageFactory(parent=dog_index_page, live=True)


@pytest.fixture
def draft_dog_status_page(dog_index_page):
    yield DogStatusPageFactory(parent=dog_index_page, title="draft", live=False)


def test_dog_index_page_statuses(dog_index_page, dog_status_page, draft_dog_status_page):
    for status_page in [dog_status_page, draft_dog_status_page]:
        DogIndexPageStatuses.objects.create(
            page=dog_index_page,
            status_page=status_page,
        )
    assert dog_index_page.status_pages() == [dog_status_page]


def test_dog_status_page_get_dogs(dog_status_page):
    assert not dog_status_page.get_dogs()

    dog_page = DogPageFactory(parent=dog_status_page)
    assert dog_status_page.get_dogs().count() == 1 
    assert dog_status_page.get_dogs().first() == dog_page
    assert sorted(dog_status_page.get_dogs()) == sorted(dog_status_page.children())


def test_fb_albums(freezer):
    freezer.move_to('2023-05-20')
    
    albums_container = FacebookAlbums()
    # date updated set to now
    assert albums_container.date_updated.date() == date(2023, 5, 20)

    # add an album
    albums_container.update_album("1", {"name": "dog 1"})
    assert albums_container.albums == {
        "1": {"name": "dog 1"}
    }
    
    # update all overwrites existing
    freezer.move_to('2023-05-22')
    albums_container.update_all(
        {"2": {"name": "dog 2"}}
    )
    assert albums_container.albums == {
        "2": {"name": "dog 2"}
    }
    # updated date set to now
    assert albums_container.date_updated.date() == date(2023, 5, 22)

    freezer.move_to('2023-05-24')
    albums_container.update_album("2", {"name": "dog 2a"})
    assert albums_container.get_album("2") == {"name": "dog 2a"}
    # updating a single album doesn't change the updated date for the whole container
    assert albums_container.date_updated.date() == date(2023, 5, 22)
    assert albums_container.get_album("1") == {}
