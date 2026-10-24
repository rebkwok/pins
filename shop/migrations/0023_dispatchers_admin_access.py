"""
Dispatchers can use the admin, for their Orders to send page (and nothing
else, so the admin home goes straight to it).
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

DISPATCHERS_GROUP = "Dispatchers"


def add_admin_access(apps, schema_editor):
    # (permissions only exist after all the migrations have run, e.g. on a new
    # database, so create them now)
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group, _ = Group.objects.get_or_create(name=DISPATCHERS_GROUP)
    group.permissions.add(
        Permission.objects.get(content_type__app_label="wagtailadmin", codename="access_admin")
    )


def remove_admin_access(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group = Group.objects.filter(name=DISPATCHERS_GROUP).first()
    if group is not None:
        group.permissions.remove(
            *Permission.objects.filter(
                content_type__app_label="wagtailadmin", codename="access_admin"
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0022_shorter_product_help"),
        ("wagtailadmin", "0006_formstate"),
    ]

    operations = [migrations.RunPython(add_admin_access, remove_admin_access)]
