"""
The shop's roles: what Shop admins and Shop managers (groups created by
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


def test_shop_manager_group():
    group = Group.objects.get(name="Shop manager")
    assert set(group.permissions.values_list("codename", flat=True)) == {
        "access_admin",
        "change_order",
        "view_order",
    }
    assert not group.collection_permissions.exists()


def test_shop_admin_menu(client):
    items = menu(client, user_in("Shop admins"))
    # (no Settings: the shop settings are in the Shop admin menu; and no
    # Wagtail help, which is about editing pages)
    # (and Dispatcher activity, where they can see the dispatchers, but not
    # change them)
    # (and no Images: they add images from products' pages)
    assert set(items) == {"orders", "dispatcher-activity", "shop-stock", "shop-admin"}
    assert items["shop-stock"] == ["categories", "products", "product-variants"]
    assert items["shop-admin"] == ["sales", "discount-codes", "shop-settings", "shop-activity"]


def test_shop_manager_menu(client):
    assert set(menu(client, user_in("Shop manager"))) == {"orders", "dispatcher-activity"}


def test_superuser_menu(client):
    items = menu(client, baker.make("auth.User", is_superuser=True))
    # grouped: site content, the shop, fundraising, then Wagtail's own
    assert list(items) == [
        "explorer",
        "images",
        "documents",
        "footer-text",
        "facebook-changes",
        "orders",
        "dispatcher-activity",
        "shop-stock",
        "shop-admin",
        "recipe-book",
        "auctions",
        "reports",
        "settings",
        "help",
    ]
    assert items["auctions"] == ["auction-categories", "auctions", "auctions-help"]

    assert "shop-settings" in items["shop-admin"]
    assert "shop-settings" not in items["settings"]


@pytest.mark.parametrize(
    "url_name,allowed",
    [
        ("wagtailsnippets_shop_product:list", True),
        ("wagtailsnippets_shop_category:list", True),
        ("wagtailsnippets_shop_discountcode:list", True),
        ("shop_orders:index", True),
        ("wagtailimages:index", True),
        ("shop_dispatchers:index", True),
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
    assert "Email new orders to" in resp.content.decode()


@pytest.mark.parametrize(
    "url_name,allowed",
    [
        ("shop_orders:index", True),
        ("wagtailsnippets_shop_product:list", False),
        ("wagtailimages:index", False),
    ],
)
def test_shop_manager_pages(client, url_name, allowed):
    client.force_login(user_in("Shop manager"))
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
    assert items["auctions"] == ["auctions", "auctions-help"]
    assert "facebook-changes" not in items
    assert client.get(reverse("auction_docs")).status_code == 200


def test_auction_categories_only(client):
    # auction categories, without managing auctions
    user = staff_with("view_auctioncategory")
    client.force_login(user)
    url = reverse("wagtailsnippets_fundraising_auctioncategory:list")
    items = menu(client, user, url=url)
    assert items["auctions"] == ["auction-categories"]
    assert client.get(reverse("auctions")).status_code == 302


def test_review_facebook_changes_permission(client):
    user = staff_with("review_facebook_changes")
    items = menu(client, user, url=reverse("facebook_changes"))
    assert "facebook-changes" in items
    assert "auctions" not in items
    assert client.post(reverse("facebook_acknowledge")).status_code == 302


def test_dispatchers_menu(client):
    # Dispatcher activity: for people who can change users (site admins), edit
    # products (shop admins) or see orders (Shop managers); not dispatchers
    url = reverse("shop_dispatchers:index")
    assert "dispatcher-activity" in menu(client, staff_with("change_user"), url=url)
    assert "dispatcher-activity" in menu(client, user_in("Shop manager"), url=url)
    dispatcher = user_in("Dispatchers")
    client.force_login(dispatcher)
    assert client.get(url).url == reverse("wagtailadmin_home")


def test_shop_admin_dispatchers_page(client, product):
    # shop admins can see the dispatchers and their products, but not change them
    dispatcher = baker.make(
        "auth.User", first_name="Ann", last_name="Smith", email="ann@test.com"
    )
    dispatcher.groups.add(Group.objects.get(name="Dispatchers"))
    product.dispatcher = dispatcher
    product.notify_dispatcher = True
    product.save()
    client.force_login(user_in("Shop admins"))
    url = reverse("shop_dispatchers:index")
    content = client.get(url).content.decode()
    assert "Ann Smith" in content
    assert 'href="mailto:ann@test.com"' in content
    assert reverse("wagtailsnippets_shop_product:edit", args=(product.pk,)) in content
    # (emailed about new orders: an icon, with a key above the table)
    assert '<span class="w-sr-only">(emailed about new orders)</span>' in content
    assert "The dispatcher is emailed about new orders for this product." in content
    assert "ask a site admin" in content
    # (no editing users, removing or adding)
    assert reverse("wagtailusers_users:edit", args=(dispatcher.pk,)) not in content
    assert 'name="remove"' not in content
    assert "Add a dispatcher" not in content
    resp = client.post(url, {"remove": dispatcher.pk})
    assert resp.url == reverse("wagtailadmin_home")
    assert dispatcher.groups.filter(name="Dispatchers").exists()


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


def test_shop_manager_start_at_orders(client):
    # their only admin page
    client.force_login(user_in("Shop manager"))
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
    # shop admins search products, shop managers orders, and page editors
    # (and superusers) pages
    assert sidebar_search_url(client, user_in("Shop admins")) == reverse(
        "wagtailsnippets_shop_product:list"
    )
    assert sidebar_search_url(client, user_in("Shop manager")) == ORDERS_URL
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


# Shop settings


def test_shop_settings_no_notify_addresses_warning(client):
    from ..models import NO_NOTIFY_ADDRESSES_WARNING, ShopSettings

    client.force_login(user_in("Shop admins"))
    url = reverse("wagtailsettings:edit", args=("shop", "shopsettings"))
    content = html_unescaped(client.get(url, follow=True))
    assert NO_NOTIFY_ADDRESSES_WARNING in content
    shop_settings = ShopSettings.load()
    shop_settings.notify_email_addresses = "shop@test.com"
    shop_settings.save()
    assert NO_NOTIFY_ADDRESSES_WARNING not in html_unescaped(client.get(url, follow=True))


def html_unescaped(resp):
    import html

    return html.unescape(resp.content.decode())


def test_admin_home_no_notify_addresses_warning(client, root_page):
    from ..models import ShopSettings

    client.force_login(user_in("Shop admins"))
    content = html_unescaped(client.get(reverse("wagtailadmin_home")))
    assert "Nobody is emailed about new shop orders: add an email address to the shop settings." in content
    shop_settings = ShopSettings.load()
    shop_settings.notify_email_addresses = "shop@test.com"
    shop_settings.save()
    content = html_unescaped(client.get(reverse("wagtailadmin_home")))
    assert "Nobody is emailed" not in content


def test_admin_home_no_warning_for_others(client, root_page):
    # (only for people who can change the shop settings)
    client.force_login(user_in("Editors"))
    assert "Nobody is emailed" not in html_unescaped(client.get(reverse("wagtailadmin_home")))


def test_message_panels_one_box(client, product):
    # the message box's style is on the message, not on its panel's section too
    # (a box within a box)
    from ..models import MessagePanel

    variant = baker.make("shop.ProductVariant", product=product, variant_name="Single")
    baker.make("shop.ProductVariant", product=product, variant_name="Pack of 5")
    client.force_login(baker.make("auth.User", is_superuser=True))
    content = client.get(
        reverse("wagtailsnippets_shop_productvariant:edit", args=(variant.pk,))
    ).content.decode()
    assert "Variants share stock" in content
    assert 'class="w-panel help-block' not in content
    # (no message: nothing shown)
    assert MessagePanel().bind_to_model(type(product)).get_bound_panel(
        instance=product, request=None, form=None
    ).get_message() is None


def test_images_menu(client):
    # shown to those with image permissions outside the Shop collection (e.g.
    # Editors), not to those with only the Shop collection's (shop admins)
    from wagtail.models import Collection, GroupCollectionPermission
    from django.contrib.auth.models import Permission

    from ..wagtail_hooks import only_shop_images

    shop_admin = user_in("Shop admins")
    assert only_shop_images(shop_admin)
    editor = user_in("Editors")
    assert not only_shop_images(editor)
    assert "images" in menu(client, editor, url=reverse("wagtailadmin_home"))
    # with a sub-collection of the Shop collection: still only the shop's
    shop = Collection.get_first_root_node().get_children().get(name="Shop")
    mugs = shop.add_child(name="Mugs")
    group = Group.objects.create(name="Mug photographers")
    GroupCollectionPermission.objects.create(
        group=group, collection=mugs, permission=Permission.objects.get(codename="add_image")
    )
    photographer = baker.make("auth.User")
    photographer.groups.add(group)
    assert only_shop_images(photographer)
    # no image permissions, or a superuser: not hidden by this
    assert not only_shop_images(baker.make("auth.User"))
    assert not only_shop_images(baker.make("auth.User", is_superuser=True))


def test_shop_admin_starts_at_welcome_page(client):
    # (their menu has submenus, e.g. Shop stock)
    client.force_login(user_in("Shop admins"))
    assert client.get(reverse("wagtailadmin_home")).status_code == 200


def test_other_plain_menus_start_at_welcome_page(client):
    # several pages that aren't the shop's order pages (e.g. Images and
    # Documents): the welcome page
    from django.contrib.auth.models import Permission
    from wagtail.models import Collection, GroupCollectionPermission

    group = Group.objects.create(name="Media")
    group.permissions.add(Permission.objects.get(codename="access_admin"))
    root = Collection.get_first_root_node()
    for codename in ["add_image", "add_document"]:
        GroupCollectionPermission.objects.create(
            group=group, collection=root, permission=Permission.objects.get(codename=codename)
        )
    user = baker.make("auth.User")
    user.groups.add(group)
    assert {"images", "documents"} <= set(menu(client, user, url=reverse("wagtailimages:index")))
    assert client.get(reverse("wagtailadmin_home")).status_code == 200
