"""
Products are dragged into order on their category's page, rather than given an
"Index" number: the Index becomes their order within their category. (The
Index is removed in 0021, as Postgres won't alter a table after updating its
rows in the same transaction.)
"""

from django.db import migrations, models


def copy_index(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    category_ids = Product.objects.values_list("category_id", flat=True).distinct()
    for category_id in category_ids:
        products = Product.objects.filter(category_id=category_id).order_by("index", "name", "id")
        for sort_order, product in enumerate(products):
            Product.objects.filter(pk=product.pk).update(sort_order=sort_order)


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0019_shop_settings_shipping_cost"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="sort_order",
            field=models.IntegerField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(copy_index, migrations.RunPython.noop),
    ]
