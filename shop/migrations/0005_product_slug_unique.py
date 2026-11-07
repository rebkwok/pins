from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shop", "0004_product_slugs_data")]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="slug",
            field=models.SlugField(
                blank=True,
                editable=False,
                help_text="For the product URL; leave blank to generate from the name",
                max_length=255,
                unique=True,
            ),
        ),
    ]
