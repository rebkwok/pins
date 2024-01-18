from django.urls import include, path

from .views import RecipeBookSubmissionCreateView, RecipeBookSubmissionDetailView, RecipeBookSubmissionUpdateView, update_form_fields
app_name = "fundraising"
urlpatterns = [
    path(
        "recipe-book/contribution/add/", 
        RecipeBookSubmissionCreateView.as_view(), 
        name="recipe_book_contribution_add"
    ),
    path(
        "recipe-book/contribution/<uuid:pk>/", 
        RecipeBookSubmissionDetailView.as_view(), 
        name="recipe_book_contribution_detail"
    ),
    path(
        "recipe-book/contribution/<uuid:pk>/edit/", 
        RecipeBookSubmissionUpdateView.as_view(), 
        name="recipe_book_contribution_edit"
    ),
    path(
        "update-form-fields", update_form_fields, name="update_form_fields"
    )
]
