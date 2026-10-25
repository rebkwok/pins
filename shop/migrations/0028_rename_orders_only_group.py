"""The Orders only group is now Shop manager (same permissions)"""

from django.db import migrations

OLD, NEW = "Orders only", "Shop manager"


def rename(apps, old, new):
    Group = apps.get_model("auth", "Group")
    if not Group.objects.filter(name=new).exists():
        Group.objects.filter(name=old).update(name=new)


def forwards(apps, schema_editor):
    rename(apps, OLD, NEW)


def backwards(apps, schema_editor):
    rename(apps, NEW, OLD)


class Migration(migrations.Migration):
    dependencies = [("shop", "0027_order_checkout_details")]

    operations = [migrations.RunPython(forwards, backwards)]
