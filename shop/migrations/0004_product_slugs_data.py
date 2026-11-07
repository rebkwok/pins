"""
Existing products' slugs, from their names (numbered if two are the same, as
shop.models.unique_product_slug)
"""

from django.db import migrations
from django.utils.text import slugify


def make_slugs(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    taken = set()
    for product in Product.objects.order_by("pk"):
        base = slugify(product.name)[:240] or "product"
        slug, number = base, 2
        while slug in taken:
            slug, number = f"{base}-{number}", number + 1
        taken.add(slug)
        product.slug = slug
        product.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [("shop", "0003_product_slug")]

    operations = [migrations.RunPython(make_slugs, migrations.RunPython.noop)]
