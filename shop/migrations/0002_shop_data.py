"""
The shop's data, the same everywhere (and needed on a new database):
- its user groups: Shop admins (the shop's admin: stock, categories, sales,
  discount codes, shipping rates, FAQs, settings and orders, and the images in
  the Shop collection), Shop manager (the orders admin) and Dispatchers (their
  items to send). Their users are site admins' business.
- the Shop image collection, which product and variant images are filed in
  (see shop.signals.file_shop_images)
- a "Standard" shipping rate (the default), and the first FAQs

(Folded from the development migrations before the first deploy.)
"""

from decimal import Decimal

from django.contrib.auth.management import create_permissions
from django.db import migrations

ADMIN_ACCESS = ("wagtailadmin", "access_admin")

GROUPS = {
    "Shop admins": [
        ADMIN_ACCESS,
        *[
            ("shop", f"{action}_{model}")
            for model in [
                "category",
                "product",
                "productvariant",
                "sale",
                "discountcode",
                "shippingrate",
                "shopfaq",
            ]
            for action in ["add", "change", "delete", "view"]
        ],
        ("shop", "change_order"),
        ("shop", "view_order"),
        ("shop", "change_shopsettings"),
    ],
    "Shop manager": [
        ADMIN_ACCESS,
        ("shop", "change_order"),
        ("shop", "view_order"),
    ],
    "Dispatchers": [ADMIN_ACCESS],
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

FAQS = [
    (
        "How much is delivery?",
        "<p>Delivery within the UK depends on what you order. Each product's page "
        "shows its delivery cost. If your order has items with different delivery "
        "costs, you only pay the highest one.</p>",
    ),
    (
        "Can I collect my order instead?",
        "<p>Yes, if you've arranged it with PINS first - please "
        '<a href="/contact-us/">contact us</a> before you order. Then choose '
        '"Collect in person" in your basket.</p>',
    ),
    (
        "Do you deliver outside the UK?",
        "<p>Our shop only delivers within the UK. If you're ordering from outside "
        'the UK, please <a href="/contact-us/">contact us</a> for shipping costs '
        "before you order.</p>",
    ),
    (
        "When will my order arrive?",
        "<p>Our shop is run by volunteers, who send out orders for us. We'll try "
        "to ship orders as soon as possible, but we can't guarantee delivery times.</p>"
        "<p>Some of our products are made to order, so they take longer to arrive. "
        "If a product is made to order, its page will say so.</p>"
    ),
    (
        "Why has only part of my order arrived?",
        "<p>Different products are sent by different volunteers, so an order with "
        "several products may arrive in more than one parcel.</p>",
    ),
]



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
        return None
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
    return shop


def add_shop_data(apps, schema_editor):
    # Models' permissions are only created after all the migrations have run
    # (e.g. on a new database), so create them now
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    GroupCollectionPermission = apps.get_model("wagtailcore", "GroupCollectionPermission")
    shop_collection = get_shop_collection(apps)
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

    ShippingRate = apps.get_model("shop", "ShippingRate")
    if not ShippingRate.objects.exists():
        ShippingRate.objects.create(name="Standard", amount=Decimal("4.99"), default=True)

    ShopFAQ = apps.get_model("shop", "ShopFAQ")
    if not ShopFAQ.objects.exists():
        for sort_order, (question, answer) in enumerate(FAQS):
            ShopFAQ.objects.create(question=question, answer=answer, sort_order=sort_order)


def remove_shop_data(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("wagtailadmin", "0006_formstate"),
        ("wagtailcore", "0097_baselogentry_uuid_action_timestamp_indexes"),
        ("wagtailimages", "0027_image_description"),
        # (after the documents migrations that give every existing group
        # permission to choose documents)
        ("wagtaildocs", "0014_alter_document_file_size"),
    ]

    operations = [migrations.RunPython(add_shop_data, remove_shop_data)]
