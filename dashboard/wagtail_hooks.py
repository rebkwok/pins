from django.urls import reverse
from django.utils.safestring import mark_safe

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
    list_display = ("title", "page_status", "category")
    menu_order = 150
    help_text = "Help"
    
    def category(self, obj):
       move_url = reverse(
            f"wagtailadmin_pages:move",
            args=[obj.id],
        )
       return mark_safe(
          f"{obj.get_parent().specific.title} <a class='button button-secondary button-small' href='{move_url}'>Change</a>"
        )
    category.short_description = "Dog Status/Category"

    def page_status(self, obj):
        return mark_safe(f"<span class='w-status w-status--primary'>{obj.status_string.title()}</span>")


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
