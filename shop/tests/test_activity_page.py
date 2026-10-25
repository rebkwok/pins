"""Shop setup > Shop activity (admin_activity.py): the shop's log entries"""

import html

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from model_bakery import baker
from wagtail.log_actions import log

from .. import activity
from ..models import DISPATCHERS_GROUP

pytestmark = pytest.mark.django_db

URL = reverse("shop_activity:index")


def user_in(group_name, **kwargs):
    user = baker.make("auth.User", **kwargs)
    user.groups.add(Group.objects.get(name=group_name))
    return user


def messages(resp):
    return [str(entry.message) for entry in resp.context["object_list"]]


@pytest.fixture
def logged(order, product, category):
    # entries for an order, a product, a category, a dispatcher, and something
    # that isn't the shop's (a dog page's group)
    dispatcher = user_in(DISPATCHERS_GROUP, first_name="Dee")
    log(product, activity.EDITED, data={"changes": ["Price: £10.00 → £12.00"]})
    log(category, activity.CATEGORY_REORDERED, data={"product": "Mug", "position": 2})
    log(dispatcher, activity.DISPATCHER_ADDED)
    log(Group.objects.get(name="Shop admins"), "wagtail.edit")
    return dispatcher


def test_shop_admin_sees_shop_entries(client, logged):
    client.force_login(user_in("Shop admins"))
    resp = client.get(URL)
    assert resp.status_code == 200
    # newest first; not the group's entry
    assert messages(resp) == [
        "Added as a dispatcher",
        "Moved Mug to position 2",
        "Edited: Price: £10.00 → £12.00",
        "Order placed (£20.00)",
    ]
    content = html.unescape(resp.content.decode())
    assert "<title>Shop activity" in content
    # each entry links to its item
    assert reverse("shop_orders:edit", args=(resp.context["object_list"][-1].object_id,)) in content


def test_superuser(client, logged):
    client.force_login(baker.make("auth.User", is_superuser=True))
    assert len(messages(client.get(URL))) == 4


@pytest.mark.parametrize("group", ["Orders only", DISPATCHERS_GROUP])
def test_others_cant_see_it(client, logged, group):
    # (Orders only users see each order's activity on its page)
    client.force_login(user_in(group))
    resp = client.get(URL)
    assert resp.status_code == 302
    # (Wagtail's permission denied redirect)
    assert resp.url == reverse("wagtailadmin_home")


def test_menu_item(client):
    client.force_login(user_in("Shop admins"))
    content = client.get(reverse("wagtailadmin_home")).content.decode()
    assert '"name": "shop-activity"' in content
    client.force_login(user_in("Orders only"))
    content = client.get(reverse("shop_orders:index")).content.decode()
    assert '"name": "shop-activity"' not in content


def test_filters(client, logged, order):
    client.force_login(user_in("Shop admins"))
    resp = client.get(URL)
    filters = resp.context["filters"]
    # only the shop's choices
    actions = [action for action, label in filters.filters["action"].extra["choices"]]
    assert set(actions) == {
        activity.ORDER_PLACED,
        activity.EDITED,
        activity.CATEGORY_REORDERED,
        activity.DISPATCHER_ADDED,
    }
    types = [str(content_type) for content_type in filters.filters["object_type"].queryset]
    assert "Group" not in " ".join(types)
    # users: those in the shop's entries
    ann = baker.make("auth.User", username="ann")
    log(order, activity.ORDER_NOTE, user=ann, data={"message": "Hi"})
    log(Group.objects.get(name="Shop admins"), "wagtail.edit", user=baker.make("auth.User", username="bob"))
    filters = client.get(URL).context["filters"]
    assert list(filters.filters["user"].extra["queryset"]) == [ann]
    # filtering by action
    resp = client.get(URL, {"action": activity.EDITED})
    assert messages(resp) == ["Edited: Price: £10.00 → £12.00"]


def test_results_and_download(client, logged):
    client.force_login(user_in("Shop admins"))
    resp = client.get(reverse("shop_activity:results"))
    assert resp.status_code == 200
    resp = client.get(URL, {"export": "xlsx"})
    assert resp.status_code == 200
    assert "shop-activity-" in resp["Content-Disposition"]
