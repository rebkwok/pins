from django.urls import reverse

from wagtail import hooks
from wagtail.admin.menu import MenuItem

from wagtail.admin.userbar import AccessibilityItem
from wagtail.contrib.modeladmin.options import (
    ModelAdmin,
    ModelAdminGroup,
    modeladmin_register,
)
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from home.models import FooterText


class FooterTextViewSet(SnippetViewSet):
    model = FooterText
    search_fields = ("body",)


class FooterSnippetViewSetGroup(SnippetViewSetGroup):
    menu_label = "Footer Text"
    menu_order = 200  # will put in 4th place (000 being 1st, 100 2nd)
    items = (FooterTextViewSet, )


@hooks.register('register_admin_menu_item')
def register_collections_menu_item():
  return MenuItem('Image Collections', reverse('wagtailadmin_collections:index'), icon_name='folder-inverse', order=200)


register_snippet(FooterSnippetViewSetGroup)
