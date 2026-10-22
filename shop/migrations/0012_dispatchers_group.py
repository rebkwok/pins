import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

DISPATCHERS_GROUP = "Dispatchers"


def create_dispatchers_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=DISPATCHERS_GROUP)


class Migration(migrations.Migration):
    """
    Dispatchers are users in the Dispatchers group, rather than Dispatcher
    objects. (The products' and order items' dispatchers aren't kept: the shop
    hadn't been deployed.)
    """

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("shop", "0011_dispatchers_and_item_shipping"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(model_name="product", name="dispatcher"),
        migrations.RemoveField(model_name="orderitem", name="dispatcher"),
        migrations.DeleteModel(name="Dispatcher"),
        migrations.AddField(
            model_name="product",
            name="dispatcher",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Who sends (or holds, for collection) this product: a user in the "
                    "Dispatchers group. Changing it doesn't change orders already placed."
                ),
                limit_choices_to={"groups__name": "Dispatchers"},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dispatched_products",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="dispatcher",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dispatched_order_items",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="dispatcher_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(create_dispatchers_group, migrations.RunPython.noop),
    ]
