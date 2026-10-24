"""Viewing the admin as a role (dashboard/view_as.py), for superusers"""

import html
import re

import pytest
from django.contrib.auth import get_user
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.urls import reverse
from model_bakery import baker

from common.users import is_view_as_user
from dashboard.view_as import SESSION_KEY, get_view_as_user, view_as_groups

pytestmark = pytest.mark.django_db

VIEW_AS_URL = reverse("view_as")
STOP_URL = reverse("stop_view_as")


@pytest.fixture
def superuser(client):
    user = baker.make("auth.User", is_superuser=True, username="admin")
    client.force_login(user)
    return user


def group(name):
    return Group.objects.get(name=name)


def test_view_as_groups():
    # groups that can use the admin (the shop's, and Wagtail's Editors and
    # Moderators), not e.g. Dispatchers (no admin access yet)
    names = [g.name for g in view_as_groups()]
    assert {"Shop admins", "Orders only", "Editors"} <= set(names)
    assert "Dispatchers" not in names
    assert names == sorted(names)


def test_view_as_page(client, superuser):
    content = html.unescape(client.get(VIEW_AS_URL).content.decode())
    nav = re.search(r'<nav[^>]*aria-label="Breadcrumb">(.*?)</nav>', content, re.S).group(1)
    assert [
        " ".join(re.sub(r"<[^>]+>", " ", item).split())
        for item in re.findall(r"<li.*?</li>", nav, re.S)
    ] == ["Home", "Settings", "View as a role"]
    assert "View as Shop admins" in content
    assert "View as Orders only" in content
    assert "Anything you do while viewing as a group is real" in content


def test_view_as_page_superusers_only(client):
    user = baker.make("auth.User")
    user.groups.add(group("Shop admins"))
    client.force_login(user)
    resp = client.get(VIEW_AS_URL)
    # (Wagtail's permission denied redirect)
    assert resp.url == reverse("wagtailadmin_home")
    resp = client.post(VIEW_AS_URL, {"group": group("Shop admins").pk})
    assert get_user(client).pk == user.pk


def test_view_as_menu_item(client, superuser):
    content = client.get(VIEW_AS_URL).content.decode()
    assert '"name": "view-as-a-role"' in content


def test_view_as(client, superuser):
    shop_admins = group("Shop admins")
    resp = client.post(VIEW_AS_URL, {"group": shop_admins.pk})
    assert resp.url == reverse("wagtailadmin_home")
    user = get_user(client)
    assert is_view_as_user(user)
    assert user.get_full_name() == "View as Shop admins"
    assert list(user.groups.all()) == [shop_admins]
    assert not user.has_usable_password()
    assert not user.is_superuser
    assert client.session[SESSION_KEY] == {
        "original_user": superuser.pk,
        "group": "Shop admins",
    }
    # the banner on admin pages, and what shop admins see
    resp = client.get(reverse("wagtailsnippets_shop_product:list"))
    content = resp.content.decode()
    assert "Viewing as <strong>Shop admins</strong>" in content
    assert f'action="{STOP_URL}"' in content
    assert client.get(VIEW_AS_URL).url == reverse("wagtailadmin_home")


def test_view_as_orders_only_starts_at_orders(client, superuser):
    client.post(VIEW_AS_URL, {"group": group("Orders only").pk})
    assert client.get(reverse("wagtailadmin_home")).url == reverse("shop_orders:index")


def test_view_as_other_group_not_allowed(client, superuser):
    resp = client.post(VIEW_AS_URL, {"group": group("Dispatchers").pk})
    assert resp.status_code == 404
    assert get_user(client) == superuser


def test_stop_view_as(client, superuser):
    client.post(VIEW_AS_URL, {"group": group("Shop admins").pk})
    resp = client.post(STOP_URL)
    assert resp.url == VIEW_AS_URL
    assert get_user(client) == superuser
    assert SESSION_KEY not in client.session
    assert [html.unescape(str(m)).strip() for m in get_messages(resp.wsgi_request)] == [
        "You're no longer viewing as Shop admins."
    ]
    assert "Viewing as" not in client.get(VIEW_AS_URL).content.decode()


def test_stop_view_as_without_admin_access(client, superuser):
    # a group whose members can't use the admin: stopping still works (it isn't
    # an admin view)
    shop_admins = group("Shop admins")
    client.post(VIEW_AS_URL, {"group": shop_admins.pk})
    shop_admins.permissions.remove(Permission.objects.get(codename="access_admin"))
    assert client.get(reverse("wagtailadmin_home")).status_code == 302
    client.post(STOP_URL)
    assert get_user(client) == superuser


def test_stop_view_as_not_viewing(client, superuser):
    assert client.post(STOP_URL).url == reverse("wagtailadmin_home")
    assert get_user(client) == superuser


def test_stop_view_as_superuser_gone(client, superuser):
    # (e.g. no longer a superuser): logged out
    client.post(VIEW_AS_URL, {"group": group("Shop admins").pk})
    superuser.is_superuser = False
    superuser.save()
    resp = client.post(STOP_URL)
    assert resp.url == reverse("wagtailadmin_login")
    assert not get_user(client).is_authenticated


def test_stop_view_as_post_only(client, superuser):
    assert client.get(STOP_URL).status_code == 405


def test_view_as_user_reused_and_reset():
    shop_admins = group("Shop admins")
    user = get_view_as_user(shop_admins)
    # e.g. changed in the admin
    user.groups.add(group("Orders only"))
    user.user_permissions.add(Permission.objects.get(codename="change_user"))
    user.is_superuser = True
    user.save()
    again = get_view_as_user(shop_admins)
    assert again.pk == user.pk
    assert list(again.groups.all()) == [shop_admins]
    assert not again.user_permissions.exists()
    assert not again.is_superuser
