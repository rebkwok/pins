from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0020_product_sort_order"),
    ]

    operations = [
        migrations.RemoveField(model_name="product", name="index"),
        migrations.AlterField(
            model_name="product",
            name="live",
            field=models.BooleanField(default=True, help_text="Shown in the shop (with its live variants). Untick to hide it."),
        ),
    ]
