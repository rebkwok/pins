from django.urls import include, path

from .views import (
    RecipeBookSubmissionCreateView, RecipeBookSubmissionDetailView, RecipeBookSubmissionUpdateView, 
    update_form_fields, method_char_count, profile_caption_char_count, submitted_recipes, user_bids, notify_winners,
    notify_auction_item_donor, notify_auction_item_winner, toggle_withdrawn_bid
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
        "bids/<slug:auction_slug>", user_bids, name="user_bids"
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
    ),
    path(
        "auction/<pk>/notify-winners", notify_winners, name="notify_auction_winners", 
    ),
    path(
        "auction/item/<pk>/notify-winner", notify_auction_item_winner, name="notify_auction_item_winner", 
    ),
    path(
        "auction/item/<pk>/notify-donor", notify_auction_item_donor, name="notify_auction_item_donor", 
    ),
    path(
        "auction/bid/<pk>/withdraw", toggle_withdrawn_bid, name="toggle_withdrawn_bid", 
    )

]
