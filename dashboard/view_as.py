"""
View the admin as a role: a superuser chooses a group, and is logged in as a
hidden preview user in just that group (so sees what its members see), until
they stop, when they're logged back in as themselves. Anything done while
viewing as a role is real.
"""

from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from wagtail.admin import messages
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin

from common.users import VIEW_AS_USERNAME_PREFIX

User = get_user_model()

# {"original_user": <the superuser's id>, "group": <the group's name>}
SESSION_KEY = "view_as"
BACKEND = "django.contrib.auth.backends.ModelBackend"


def view_as_groups():
    """The groups that can use the admin (so can be viewed as)"""
    return Group.objects.filter(
        permissions__content_type__app_label="wagtailadmin",
        permissions__codename="access_admin",
    ).order_by("name")


def get_view_as_user(group):
    """The group's preview user (created if necessary), in just that group"""
    user, created = User.objects.get_or_create(
        username=f"{VIEW_AS_USERNAME_PREFIX}{group.pk}",
    )
    if created:
        # (it can't log in, only be viewed as)
        user.set_unusable_password()
    # (the admin shows users' first names)
    user.first_name = f"View as {group.name}"
    user.last_name = ""
    user.is_active = True
    user.is_staff = user.is_superuser = False
    user.save()
    user.groups.set([group])
    user.user_permissions.clear()
    return user


class ViewAsView(WagtailAdminTemplateMixin, TemplateView):
    """Settings > View as a role: choose a group to view the admin as"""

    template_name = "dashboard/view_as.html"
    page_title = "View as a role"
    header_icon = "view"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return self.breadcrumbs_items + [
            {"url": None, "label": "Settings"},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["groups"] = view_as_groups()
        return context

    def post(self, request, *args, **kwargs):
        group = get_object_or_404(view_as_groups(), pk=request.POST.get("group"))
        original_user = request.user
        login(request, get_view_as_user(group), backend=BACKEND)
        # (after logging in, which starts a new session)
        request.session[SESSION_KEY] = {
            "original_user": original_user.pk,
            "group": group.name,
        }
        return redirect("wagtailadmin_home")


@require_POST
def stop_view_as(request):
    """
    Go back to being the superuser who started viewing as a role. (Not an admin
    view: the role may not be able to use the admin.)
    """
    data = request.session.get(SESSION_KEY)
    if not data:
        return redirect("wagtailadmin_home")
    original_user = User.objects.filter(
        pk=data["original_user"], is_superuser=True, is_active=True
    ).first()
    if original_user is None:
        logout(request)
        return redirect("wagtailadmin_login")
    login(request, original_user, backend=BACKEND)
    messages.success(request, f"You're no longer viewing as {data['group']}.")
    return redirect(reverse("view_as"))
