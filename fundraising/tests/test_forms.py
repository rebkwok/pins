import pytest

from ..forms import RecipeBookContrbutionForm


pytestmark = pytest.mark.django_db


always_required = ["name", "email", "email1", "page_type"]
recipe_required_fields =[
    "title", "preparation_time", "cook_time", "servings", "ingredients", "method",
    "submitted_by", "profile_image"
]
never_required = ["profile_caption", "photo_caption"]

@pytest.mark.parametrize(
    "page_type,required,not_required",
    [
        (
            "single",
            [*always_required, *recipe_required_fields],
            [*never_required, "photo", "photo_title"]
        ),
        (
            "double",
            [*always_required, *recipe_required_fields],
            [*never_required, "photo", "photo_title"]
        ),
        (
            "single_with_facing",
            [*always_required, *recipe_required_fields, "photo", "photo_title"],
            never_required
        ),
        (
            "photo",
            [*always_required, "photo", "photo_title"],
            [*recipe_required_fields, *never_required]
        ),
    ]
)
def test_recipe_contribution_form_required_fields(page_type, required, not_required):
    form = RecipeBookContrbutionForm(page_type=page_type)
    for field in required:
        assert form.fields[field].required, field
    for field in not_required:
        assert not form.fields[field].required, field
