from django.db import migrations, models


class Migration(migrations.Migration):
    """Products' slugs (web addresses): added, then made (0004), then unique (0005)"""

    dependencies = [("shop", "0002_shop_data")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="slug",
            field=models.SlugField(blank=True, default="", max_length=255),
            preserve_default=False,
        ),
    ]
