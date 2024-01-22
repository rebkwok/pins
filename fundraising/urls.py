from django.urls import include, path

from .views import (
    RecipeBookSubmissionCreateView, RecipeBookSubmissionDetailView, RecipeBookSubmissionUpdateView, 
    update_form_fields, method_char_count, profile_caption_char_count, submitted_recipes
)
app_name = "fundraising"
urlpatterns = [
    path(
        "recipe-book/contribution/add/", 
        RecipeBookSubmissionCreateView.as_view(), 
        name="recipe_book_contribution_add"
    ),
    path(
        "recipe-book/contribution/<str:pk>/", 
        RecipeBookSubmissionDetailView.as_view(), 
        name="recipe_book_contribution_detail"
    ),
    path(
        "recipe-book/contribution/<str:pk>/edit/", 
        RecipeBookSubmissionUpdateView.as_view(), 
        name="recipe_book_contribution_edit"
    ),
    path(
        "recipe-book/recipes", submitted_recipes, name="submitted_recipes"
    ),
    path(
        "update-form-fields", update_form_fields, name="update_form_fields"
    ),
    path(
        "count/method", method_char_count, name="method_char_count"
    ),
    path(
        "count/profile", profile_caption_char_count, name="profile_caption_char_count"
    )
]
