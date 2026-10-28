"""The shop's data migration (0002_shop_data): groups, the Shop collection, the first shipping rate and FAQs"""
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("shop", "0001_initial")]
AFTER = [("shop", "0002_shop_data")]

SHOP_GROUPS = ["Dispatchers", "Shop admins", "Shop manager"]


def migrate(targets):
    """Migrate to targets, returning the historical models"""
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def root_page():
    # (replaces conftest's autouse root page: transactional tests flush the
    # database, including the default locale that the root page needs)
    yield None


@pytest.fixture
def migrations():
    """Migrate back to the latest migrations afterwards"""
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    yield migrate
    migrate(leaf_nodes)


def permissions(group):
    return {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in group.permissions.select_related("content_type")
    }


def root_collection(apps):
    # (the root collection may have been flushed by other tests; and the Shop
    # collection may be left from before)
    Collection = apps.get_model("wagtailcore", "Collection")
    root = Collection.objects.filter(depth=1).first() or Collection.objects.create(
        name="Root", path="0001", depth=1, numchild=0
    )
    Collection.objects.filter(depth__gt=1).delete()
    Collection.objects.filter(pk=root.pk).update(numchild=0)
    return root


@pytest.mark.django_db(transaction=True)
def test_shop_data(migrations):
    apps = migrations(BEFORE)
    root = root_collection(apps)
    apps.get_model("auth", "Group").objects.filter(name__in=SHOP_GROUPS).delete()

    apps = migrations(AFTER)
    Group = apps.get_model("auth", "Group")
    shop_admins = Group.objects.get(name="Shop admins")
    assert permissions(shop_admins) == {
        "wagtailadmin.access_admin",
        *{
            f"shop.{action}_{model}"
            for model in ["category", "product", "productvariant", "sale", "discountcode", "shippingrate", "shopfaq"]
            for action in ["add", "change", "delete", "view"]
        },
        "shop.change_order",
        "shop.view_order",
        "shop.change_shopsettings",
    }
    assert permissions(Group.objects.get(name="Shop manager")) == {
        "wagtailadmin.access_admin",
        "shop.change_order",
        "shop.view_order",
    }
    assert permissions(Group.objects.get(name="Dispatchers")) == {"wagtailadmin.access_admin"}

    # the Shop collection, with the shop admins' image permissions in it
    Collection = apps.get_model("wagtailcore", "Collection")
    shop = Collection.objects.get(name="Shop")
    assert (shop.depth, shop.path) == (2, root.path + "0001")
    assert Collection.objects.get(pk=root.pk).numchild == 1
    collection_permissions = apps.get_model("wagtailcore", "GroupCollectionPermission").objects.filter(
        group=shop_admins
    )
    assert {p.collection_id for p in collection_permissions} == {shop.pk}
    assert {p.permission.codename for p in collection_permissions} == {"add_image", "change_image", "choose_image"}

    # the default shipping rate, and the first FAQs
    rate = apps.get_model("shop", "ShippingRate").objects.get()
    assert (rate.name, str(rate.amount), rate.default) == ("Standard", "4.99", True)
    faqs = apps.get_model("shop", "ShopFAQ").objects.order_by("sort_order")
    assert [faq.question for faq in faqs][:2] == ["How much is delivery?", "Can I collect my order instead?"]
    assert [faq.sort_order for faq in faqs] == [0, 1, 2, 3, 4]

    # and back: the groups are removed
    apps = migrations(BEFORE)
    assert not apps.get_model("auth", "Group").objects.filter(name__in=SHOP_GROUPS).exists()


@pytest.mark.django_db(transaction=True)
def test_shop_data_existing(migrations):
    # (e.g. run again): the existing Shop collection, rates and FAQs are kept
    apps = migrations(BEFORE)
    root = root_collection(apps)
    Collection = apps.get_model("wagtailcore", "Collection")
    events = Collection.objects.create(name="Events", path=root.path + "0001", depth=2, numchild=0)
    Collection.objects.filter(pk=root.pk).update(numchild=1)
    ShippingRate = apps.get_model("shop", "ShippingRate")
    ShippingRate.objects.all().delete()
    ShippingRate.objects.create(name="Small items", amount="3.50", default=True)
    ShopFAQ = apps.get_model("shop", "ShopFAQ")
    ShopFAQ.objects.all().delete()
    ShopFAQ.objects.create(question="Our own?", answer="<p>Yes.</p>", sort_order=0)

    apps = migrations(AFTER)
    Collection = apps.get_model("wagtailcore", "Collection")
    # (after the existing collection)
    assert Collection.objects.get(name="Shop").path == root.path + "0002"
    assert Collection.objects.get(pk=events.pk).name == "Events"
    assert list(apps.get_model("shop", "ShippingRate").objects.values_list("name", flat=True)) == ["Small items"]
    assert list(apps.get_model("shop", "ShopFAQ").objects.values_list("question", flat=True)) == ["Our own?"]
