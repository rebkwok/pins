import pytest

from model_bakery import baker

from ..models import RecipeBookSubmission

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "page_type,cost",
    [
        ("single", 5),
        ("double", 10),
        ("single_with_facing", 10),
        ("photo", 5)
    ]
)
def test_recipe_book_submission_page_type_cost(page_type, cost):
    submission = baker.make(RecipeBookSubmission, page_type=page_type)
    assert submission.cost == cost


@pytest.mark.parametrize(
    "paid,processing,complete,expected",
    [
        (False, False, False, "Payment pending"),
        (True, False, False, "Paid"),
        (True, False, True, "Paid and complete"),
        (True, False, True, "Paid and complete"),
        (True, True, False, "Paid, processing submission"),
    ]
)
def test_recipe_book_submission_status(paid, processing, complete, expected):
    submission = baker.make(RecipeBookSubmission, paid=paid, processing=processing, complete=complete)
    assert submission.status() == expected
