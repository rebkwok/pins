# Generated by Django 4.2.3 on 2023-08-30 14:07

from django.db import migrations, models
import django.db.models.deletion
import modelcluster.fields


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0003_orderformpage_orderformfield"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="orderformpage",
            name="product_cost",
        ),
        migrations.CreateModel(
            name="ProductVariant",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "sort_order",
                    models.IntegerField(blank=True, editable=False, null=True),
                ),
                ("description", models.CharField(blank=True, max_length=250)),
                ("cost", models.DecimalField(decimal_places=2, max_digits=10)),
                (
                    "page",
                    modelcluster.fields.ParentalKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="product_variants",
                        to="home.orderformpage",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order"],
                "abstract": False,
            },
        ),
    ]