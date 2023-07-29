from django.urls import reverse

from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from wagtail.admin.userbar import AccessibilityItem
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from home.models import FooterText
from dogs.models import DogPage


# ensure our modeladmin is created
class DogPageModelAdmin(ModelAdmin):
    model = DogPage
    menu_order = 150


class FooterTextViewSet(SnippetViewSet):
    model = FooterText
    search_fields = ("body",)
    add_to_admin_menu = True
    menu_label = "Footer Text"
    menu_order = 400  # will put in 5th place (000 being 1st, 100 2nd)


@hooks.register('register_admin_menu_item')
def register_collections_menu_item():
  return MenuItem('Collections', reverse('wagtailadmin_collections:index'), icon_name='folder-inverse', order=200)


register_snippet(FooterTextViewSet)
modeladmin_register(DogPageModelAdmin)
