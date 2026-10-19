import django.db.models.deletion
import modelcluster.fields
from django.db import migrations, models


def move_product_images(apps, schema_editor):
    """Each product's image becomes its first product image"""
    Product = apps.get_model("shop", "Product")
    ProductImage = apps.get_model("shop", "ProductImage")
    ProductImage.objects.bulk_create(
        ProductImage(product=product, image_id=product.image_id, sort_order=0)
        for product in Product.objects.filter(image__isnull=False)
    )


def restore_product_images(apps, schema_editor):
    """Each product's first product image becomes its image"""
    Product = apps.get_model("shop", "Product")
    ProductImage = apps.get_model("shop", "ProductImage")
    for product in Product.objects.all():
        first = ProductImage.objects.filter(product=product).order_by("sort_order").first()
        if first is not None:
            product.image_id = first.image_id
            product.save(update_fields=["image"])


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0006_shipping_method_default_delivery'),
        ('wagtailimages', '0027_image_description'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(blank=True, editable=False, null=True)),
                ('alt_text', models.CharField(blank=True, default='', help_text="Optional description of the image for people using screen readers. If blank, the image's own description (or title) is used.", max_length=255)),
                ('image', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='wagtailimages.image')),
                ('product', modelcluster.fields.ParentalKey(on_delete=django.db.models.deletion.CASCADE, related_name='product_images', to='shop.product')),
            ],
            options={
                'ordering': ['sort_order'],
                'abstract': False,
            },
        ),
        migrations.RunPython(move_product_images, restore_product_images),
        migrations.RemoveField(
            model_name='product',
            name='image',
        ),
    ]
