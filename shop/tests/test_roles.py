"""
The shop's roles: what Shop admins and Orders only users (groups created by
migration 0017) see in the admin menu and can use, and the admin pages that
need their own permissions.
"""

import json
import re

from django.core.files.uploadedfile import SimpleUploadedFile

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from model_bakery import baker

pytestmark = pytest.mark.django_db

ORDERS_URL = reverse("shop_orders:index")


def user_in(*groups, **kwargs):
    user = baker.make("auth.User", **kwargs)
    user.groups.add(*Group.objects.filter(name__in=groups))
    return user


def menu(client, user, url=ORDERS_URL):
    """The admin menu on the page, as {item name: [submenu item names]}"""
    client.force_login(user)
    content = client.get(url).content.decode()
    props = json.loads(
        re.search(
            r'<script id="wagtail-sidebar-props" type="application/json">(.*?)</script>',
            content,
            re.S,
        ).group(1)
    )
    (main_menu,) = [
        module for module in props["modules"] if module["_type"].endswith("MainMenuModule")
    ]

    def name(item):
        # (repeated values are packed as {"_val": value, "_id": id})
        value = item["_args"][0]["name"]
        return value["_val"] if isinstance(value, dict) else value

    def items(menu_items):
        return {
            name(item): (
                # (the Pages item has its start page's id instead)
                list(items(item["_args"][1]))
                if len(item["_args"]) > 1 and isinstance(item["_args"][1], list)
                else []
            )
            for item in menu_items
        }

    return items(main_menu["_args"][0])


def test_shop_admins_group():
    group = Group.objects.get(name="Shop admins")
    permissions = set(group.permissions.values_list("codename", flat=True))
    assert {
        "access_admin",
        "add_product",
        "change_productvariant",
        "delete_category",
        "change_sale",
        "add_discountcode",
        "change_order",
        "change_shopsettings",
    } <= permissions
    # orders can't be added or deleted; users and dispatchers aren't theirs
    assert not {"add_order", "delete_order", "change_user"} & permissions
    # images in the Shop collection only
    assert set(
        group.collection_permissions.values_list("collection__name", "permission__codename")
    ) == {("Shop", "add_image"), ("Shop", "change_image"), ("Shop", "choose_image")}


def test_orders_only_group():
    group = Group.objects.get(name="Orders only")
    assert set(group.permissions.values_list("codename", flat=True)) == {
        "access_admin",
        "change_order",
        "view_order",
    }
    assert not group.collection_permissions.exists()


def test_shop_admin_menu(client):
    items = menu(client, user_in("Shop admins"))
    # (no Settings: the shop settings are in the Shop Stock menu; and no Wagtail
    # help, which is about editing pages)
    assert set(items) == {"orders", "shop-stock", "images"}
    # not the dispatchers (site admins manage them)
    assert items["shop-stock"] == [
        "categories",
        "products",
        "product-variants",
        "sales",
        "discount-codes",
        "shop-settings",
    ]


def test_orders_only_menu(client):
    assert set(menu(client, user_in("Orders only"))) == {"orders"}


def test_superuser_menu(client):
    items = menu(client, baker.make("auth.User", is_superuser=True))
    assert {"auctions", "auctions-help", "facebook-changes", "orders", "help"} <= set(items)
    assert "dispatchers" in items["shop-stock"]
    assert "shop-settings" in items["shop-stock"]
    assert "shop-settings" not in items["settings"]


@pytest.mark.parametrize(
    "url_name,allowed",
    [
        ("wagtailsnippets_shop_product:list", True),
        ("wagtailsnippets_shop_category:list", True),
        ("wagtailsnippets_shop_discountcode:list", True),
        ("shop_orders:index", True),
        ("wagtailimages:index", True),
        ("shop_dispatchers:index", False),
        ("auctions", False),
        ("auction_docs", False),
        ("facebook_changes", False),
        ("wagtailusers_users:index", False),
    ],
)
def test_shop_admin_pages(client, url_name, allowed):
    client.force_login(user_in("Shop admins"))
    resp = client.get(reverse(url_name))
    if allowed:
        assert resp.status_code == 200
    else:
        # Wagtail redirects with a "permission denied" message
        assert resp.status_code == 302
        assert resp.url == reverse("wagtailadmin_home")


def test_shop_admin_shop_settings(client):
    client.force_login(user_in("Shop admins"))
    resp = client.get(
        reverse("wagtailsettings:edit", args=("shop", "shopsettings")), follow=True
    )
    assert resp.status_code == 200
    assert "Notify email addresses" in resp.content.decode()


@pytest.mark.parametrize(
    "url_name,allowed",
    [
        ("shop_orders:index", True),
        ("wagtailsnippets_shop_product:list", False),
        ("wagtailimages:index", False),
    ],
)
def test_orders_only_pages(client, url_name, allowed):
    client.force_login(user_in("Orders only"))
    resp = client.get(reverse(url_name))
    assert resp.status_code == (200 if allowed else 302)


def staff_with(codename):
    user = baker.make("auth.User")
    user.user_permissions.add(
        Permission.objects.get(codename="access_admin"),
        Permission.objects.get(codename=codename),
    )
    return user


def test_manage_auctions_permission(client):
    items = menu(client, staff_with("manage_auctions"), url=reverse("auctions"))
    assert items["auctions"] == ["auctions"]
    assert "auctions-help" in items
    assert "facebook-changes" not in items
    assert client.get(reverse("auction_docs")).status_code == 200


def test_auction_categories_only(client):
    # auction categories, without managing auctions
    user = staff_with("view_auctioncategory")
    client.force_login(user)
    url = reverse("wagtailsnippets_fundraising_auctioncategory:list")
    items = menu(client, user, url=url)
    assert items["auctions"] == ["auction-categories"]
    assert "auctions-help" not in items
    assert client.get(reverse("auctions")).status_code == 302


def test_review_facebook_changes_permission(client):
    user = staff_with("review_facebook_changes")
    items = menu(client, user, url=reverse("facebook_changes"))
    assert "facebook-changes" in items
    assert "auctions" not in items
    assert client.post(reverse("facebook_acknowledge")).status_code == 302


def test_dispatchers_menu_needs_change_user(client):
    user = staff_with("change_user")
    user.groups.add(Group.objects.get(name="Shop admins"))
    assert "dispatchers" in menu(client, user)["shop-stock"]


# The Shop image collection


def test_shop_admin_only_sees_shop_images(client):
    from wagtail.models import Collection

    from ..models import get_shop_collection

    from wagtail_factories import ImageFactory

    shop_image = ImageFactory(title="Mug photo", collection=get_shop_collection())
    other = ImageFactory(title="Dog photo", collection=Collection.get_first_root_node())
    client.force_login(user_in("Shop admins"))
    resp = client.get(reverse("wagtailimages:index"))
    assert list(resp.context["images"]) == [shop_image]
    resp = client.get(reverse("wagtailimages_chooser:choose"))
    assert "Mug photo" in resp.content.decode()
    assert "Dog photo" not in resp.content.decode()
    # uploads go in the Shop collection, the only one they can add to (so the
    # upload form doesn't ask)
    resp = client.get(reverse("wagtailimages:add"))
    assert "collection" not in resp.context["form"].fields
    upload = ImageFactory.build().file
    upload.file.seek(0)
    client.post(
        reverse("wagtailimages:add"),
        {"title": "New mug", "file": SimpleUploadedFile("mug.jpg", upload.read())},
    )
    from wagtail.images.models import Image

    assert Image.objects.get(title="New mug").collection == get_shop_collection()
    assert other.collection.is_root()


def test_shop_settings_menu_link(client):
    items_url = reverse("wagtailsettings:edit", args=("shop", "shopsettings"))
    client.force_login(user_in("Shop admins"))
    assert items_url in client.get(ORDERS_URL).content.decode()


def test_help_menu_for_page_editors(client):
    # e.g. Wagtail's Editors group, which can edit pages
    user = user_in("Editors")
    assert "help" in menu(client, user, url=reverse("wagtailadmin_pages:search"))


# The admin home


def test_orders_only_start_at_orders(client):
    # their only admin page
    client.force_login(user_in("Orders only"))
    resp = client.get(reverse("wagtailadmin_home"))
    assert resp.url == ORDERS_URL


def test_shop_admins_welcome_page(client, root_page):
    # more than one admin page, so the welcome page, without "Search all pages"
    # (they have no pages)
    client.force_login(user_in("Shop admins"))
    resp = client.get(reverse("wagtailadmin_home"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Welcome to the PINS Admin" in content
    assert "Search all pages" not in content


def test_editors_welcome_page_search(client, root_page):
    client.force_login(user_in("Editors"))
    content = client.get(reverse("wagtailadmin_home")).content.decode()
    assert "Search all pages" in content


# View-as preview users (dashboard/view_as.py) aren't real dispatchers


def test_view_as_users_not_dispatchers(client):
    from common.users import VIEW_AS_USERNAME_PREFIX

    from ..admin_views import AddDispatcherForm
    from ..models import Product, dispatcher_choices

    dispatchers = Group.objects.get(name="Dispatchers")
    real = baker.make("auth.User", first_name="Ann")
    preview = baker.make("auth.User", username=f"{VIEW_AS_USERNAME_PREFIX}99")
    real.groups.add(dispatchers)
    preview.groups.add(dispatchers)
    from django.contrib.auth import get_user_model

    choices = get_user_model().objects.filter(dispatcher_choices())
    assert list(choices) == [real]
    from wagtail.admin.panels import get_edit_handler

    form = get_edit_handler(Product).get_form_class()()
    assert list(form.fields["dispatcher"].queryset) == [real]
    assert preview not in AddDispatcherForm().fields["user"].queryset
    client.force_login(baker.make("auth.User", is_superuser=True))
    resp = client.get(reverse("shop_dispatchers:index"))
    assert list(resp.context["dispatchers"]) == [real]
    resp = client.get(ORDERS_URL)
    assert preview.pk not in [
        user.pk for user in resp.context["filters"].filters["dispatcher"].queryset
    ]


# Searching


@pytest.mark.parametrize(
    "url_name,query,found,not_found",
    [
        ("wagtailsnippets_shop_product:list", "Mugs", "Mug", "Card"),
        ("wagtailsnippets_shop_product:list", "card", "Card", "Mug"),
        ("wagtailsnippets_shop_productvariant:list", "blue", "Mug - Blue", "Card"),
        ("wagtailsnippets_shop_category:list", "mug", "Mugs", "Cards"),
        ("wagtailsnippets_shop_sale:list", "summer", "Summer sale", "Winter sale"),
    ],
)
def test_shop_lists_search(client, url_name, query, found, not_found):
    mugs = baker.make("shop.Category", title="Mugs")
    cards = baker.make("shop.Category", title="Cards")
    mug = baker.make("shop.Product", name="Mug", category=mugs)
    baker.make("shop.ProductVariant", product=mug, variant_name="Blue")
    card = baker.make("shop.Product", name="Card", category=cards)
    baker.make("shop.ProductVariant", product=card, variant_name="Single")
    baker.make("shop.Sale", name="Summer sale")
    baker.make("shop.Sale", name="Winter sale")
    client.force_login(user_in("Shop admins"))
    resp = client.get(reverse(url_name), {"q": query})
    # (e.g. a sale is shown with its dates)
    shown = " | ".join(str(item) for item in resp.context["object_list"])
    assert found in shown
    assert not_found not in shown


def sidebar_search_url(client, user):
    client.force_login(user)
    content = client.get(ORDERS_URL).content.decode()
    props = json.loads(
        re.search(
            r'<script id="wagtail-sidebar-props" type="application/json">(.*?)</script>',
            content,
            re.S,
        ).group(1)
    )
    (search,) = [m for m in props["modules"] if m["_type"].endswith("SearchModule")]
    return search["_args"][0]


def test_sidebar_search(client):
    # shop admins search products, orders only users orders, and page editors
    # (and superusers) pages
    assert sidebar_search_url(client, user_in("Shop admins")) == reverse(
        "wagtailsnippets_shop_product:list"
    )
    assert sidebar_search_url(client, user_in("Orders only")) == ORDERS_URL
    assert sidebar_search_url(
        client, baker.make("auth.User", is_superuser=True)
    ) == reverse("wagtailadmin_pages:search")


def test_search_other_areas(client):
    # a product search offers the same search in orders and images
    client.force_login(user_in("Shop admins"))
    content = client.get(
        reverse("wagtailsnippets_shop_product:list_results"), {"q": "mug"}
    ).content.decode()
    assert f'href="{ORDERS_URL}?q=mug"' in content
    assert f'href="{reverse("wagtailimages:index")}?q=mug"' in content
    content = client.get(reverse("shop_orders:index_results"), {"q": "mug"}).content.decode()
    assert f'href="{reverse("wagtailsnippets_shop_product:list")}?q=mug"' in content
