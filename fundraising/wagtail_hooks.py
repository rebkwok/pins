from django.urls import reverse
from django.utils.safestring import mark_safe

from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from .models import RecipeBookSubmission
from paypal.standard.ipn.models import PayPalIPN


# ensure our modeladmin is created
class RecipeBookSubmissionViewSet(SnippetViewSet):
    model = RecipeBookSubmission
    list_display = ("name", "email", "page_type_verbose", "formatted_cost", BooleanColumn("paid"), BooleanColumn("complete"))
    menu_order = 400
    icon = "tablet-alt"


class PayPalIPNViewSet(SnippetViewSet):
    model = PayPalIPN
    fields = ("invoice", "payment_status", "flag", "flag_info")
    read_only_fields = fields


class RecipeBookGroup(SnippetViewSetGroup):
    menu_label = "Recipe Book"
    menu_icon = "tablet-alt"
    items = (RecipeBookSubmissionViewSet, PayPalIPNViewSet)
    menu_order = 200


register_snippet(RecipeBookGroup)
