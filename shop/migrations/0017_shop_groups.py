"""
The shop's user groups (the same everywhere):
- Shop admins: the shop parts of the admin (shop stock, categories, sales,
  discount codes, shop settings and orders), and the images in the Shop
  collection (for product images)
- Orders only: the orders admin
(Dispatchers, created in 0012, are site admins' business, as are the users.)

Also the Shop image collection, which product and variant images are filed in
(see shop.signals.file_shop_images): the images already used by products and
variants are moved there from the root collection.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

ADMIN_ACCESS = ("wagtailadmin", "access_admin")

GROUPS = {
    "Shop admins": [
        ADMIN_ACCESS,
        *[
            ("shop", f"{action}_{model}")
            for model in ["category", "product", "productvariant", "sale", "discountcode"]
            for action in ["add", "change", "delete", "view"]
        ],
        ("shop", "change_order"),
        ("shop", "view_order"),
        ("shop", "change_shopsettings"),
    ],
    "Orders only": [
        ADMIN_ACCESS,
        ("shop", "change_order"),
        ("shop", "view_order"),
    ],
}

SHOP_COLLECTION = "Shop"

# Permissions in the Shop collection (and so its child collections)
COLLECTION_PERMISSIONS = {
    "Shop admins": [
        ("wagtailimages", "add_image"),
        ("wagtailimages", "change_image"),
        ("wagtailimages", "choose_image"),
    ],
}


def get_permission(apps, app_label, codename):
    Permission = apps.get_model("auth", "Permission")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def base36(number):
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    result = ""
    while number:
        number, remainder = divmod(number, 36)
        result = digits[remainder] + result
    return result.rjust(4, "0")


def get_shop_collection(apps):
    """
    The Shop collection, under the root collection (added with the historical
    models, which don't have treebeard's add_child)
    """
    Collection = apps.get_model("wagtailcore", "Collection")
    root = Collection.objects.filter(depth=1).first()
    if root is None:
        return None, None
    children = Collection.objects.filter(path__startswith=root.path, depth=2)
    shop = children.filter(name=SHOP_COLLECTION).first()
    if shop is None:
        last = children.order_by("-path").values_list("path", flat=True).first()
        step = int(last[-4:], 36) + 1 if last else 1
        shop = Collection.objects.create(
            name=SHOP_COLLECTION, path=root.path + base36(step), depth=2, numchild=0
        )
        root.numchild = children.count()
        root.save(update_fields=["numchild"])
    return root, shop


def create_groups(apps, schema_editor):
    # Models' permissions are only created after all the migrations have run
    # (e.g. on a new database), so create them now
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    GroupCollectionPermission = apps.get_model("wagtailcore", "GroupCollectionPermission")
    root, shop_collection = get_shop_collection(apps)
    for name, permissions in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.add(
            *(get_permission(apps, *permission) for permission in permissions)
        )
        if shop_collection is not None:
            for permission in COLLECTION_PERMISSIONS.get(name, []):
                GroupCollectionPermission.objects.get_or_create(
                    group=group,
                    collection=shop_collection,
                    permission=get_permission(apps, *permission),
                )

    if shop_collection is not None:
        # The shop's images that aren't filed in a collection
        Image = apps.get_model("wagtailimages", "Image")
        ProductImage = apps.get_model("shop", "ProductImage")
        ProductVariant = apps.get_model("shop", "ProductVariant")
        image_ids = set(ProductImage.objects.values_list("image_id", flat=True))
        image_ids.update(
            ProductVariant.objects.exclude(image=None).values_list("image_id", flat=True)
        )
        Image.objects.filter(id__in=image_ids, collection=root).update(
            collection=shop_collection
        )


def delete_groups(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0016_delete_categorypage"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("wagtailadmin", "0006_formstate"),
        ("wagtailcore", "0097_baselogentry_uuid_action_timestamp_indexes"),
        ("wagtailimages", "0027_image_description"),
        # (after the documents migrations that give every existing group
        # permission to choose documents)
        ("wagtaildocs", "0014_alter_document_file_size"),
    ]

    operations = [migrations.RunPython(create_groups, delete_groups)]
