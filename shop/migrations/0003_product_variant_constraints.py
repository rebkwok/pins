from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0002_productvariant_blank_nulls"),
    ]

    operations = [
        migrations.AlterField(
            model_name='productvariant',
            name='colour',
            field=models.CharField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='productvariant',
            name='price',
            field=models.DecimalField(blank=True, decimal_places=2, help_text="Leave blank to use the product's price (which then also applies if the product's price is changed).", max_digits=18, null=True),
        ),
        migrations.AlterField(
            model_name='productvariant',
            name='size',
            field=models.CharField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='productvariant',
            name='variant_name',
            field=models.CharField(blank=True, default='', help_text='Can be left blank if there is only one variant for this product, or if it only varies by colour and/or size.', max_length=255, verbose_name='Variant name'),
        ),
        migrations.AddConstraint(
            model_name='productvariant',
            constraint=models.UniqueConstraint(fields=('product', 'variant_name', 'colour', 'size'), name='unique_product_variant', violation_error_message='This product already has a variant with this name, colour and size.'),
        ),
    ]
