from django.urls import reverse
from django.utils.safestring import mark_safe

from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .models import RecipeBookSubmission


# ensure our modeladmin is created
class RecipeBookSubmissionViewSet(SnippetViewSet):
    model = RecipeBookSubmission
    add_to_admin_menu = True
    list_display = ("name", "email", "page_type_verbose", "formatted_cost", BooleanColumn("paid"), BooleanColumn("complete"))
    menu_order = 400
    icon = "tablet-alt"



register_snippet(RecipeBookSubmissionViewSet)
