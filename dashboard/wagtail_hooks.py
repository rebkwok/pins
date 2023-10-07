from django.urls import reverse
from django.utils.safestring import mark_safe

from wagtail import hooks
from wagtail.admin.menu import MenuItem

from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from home.models import FooterText
from dogs.models import DogPage


# ensure our modeladmin is created
class DogPageViewSet(SnippetViewSet):
    model = DogPage
    add_to_admin_menu = True
    list_display = ("title", "page_status", "category")
    menu_order = 150
    help_text = "Help"


class FooterTextViewSet(SnippetViewSet):
    model = FooterText
    search_fields = ("body",)
    add_to_admin_menu = True
    menu_label = "Footer Text"
    menu_order = 400  # will put in 5th place (000 being 1st, 100 2nd)


class CollectionMenuItem(MenuItem): 
    def is_shown(self, request):
        return request.user.is_superuser


@hooks.register('register_admin_menu_item')
def register_collections_menu_item():
  return CollectionMenuItem('Collections', reverse('wagtailadmin_collections:index'), icon_name='folder-inverse', order=200)


register_snippet(FooterTextViewSet)
register_snippet(DogPageViewSet)
