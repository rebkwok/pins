from django.urls import path, reverse
from django.utils.safestring import mark_safe

from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.permission_policies.pages import PagePermissionPolicy

from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from home.models import FooterText
from .view_as import ViewAsView
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


@hooks.register('construct_main_menu')
def hide_help_menu(request, menu_items):
    # Wagtail's help (what's new, the editor guide) is about editing pages, so
    # it's only for users who can edit pages, not e.g. shop admins
    if not PagePermissionPolicy().user_has_any_permission(
        request.user, ["add", "change", "publish"]
    ):
        menu_items[:] = [item for item in menu_items if item.name != "help"]


class SuperuserMenuItem(MenuItem):
    def is_shown(self, request):
        return request.user.is_superuser


@hooks.register('register_settings_menu_item')
def register_view_as_menu_item():
    return SuperuserMenuItem('View as a role', reverse('view_as'), icon_name='view', order=1000)


@hooks.register('register_admin_urls')
def register_view_as_url():
    return [path('view-as/', ViewAsView.as_view(), name='view_as')]


register_snippet(FooterTextViewSet)
register_snippet(DogPageViewSet)
