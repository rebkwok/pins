# Generated by Django 4.2.3 on 2023-09-02 12:19

from django.db import migrations, models
import django.db.models.deletion
import wagtail.fields


class Migration(migrations.Migration):

    dependencies = [
        ("wagtailimages", "0025_alter_image_file_alter_rendition_file"),
        ("shop", "0005_productitem_delete_productpage"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="body",
            field=wagtail.fields.RichTextField(blank=True, verbose_name="Page body"),
        ),
        migrations.AddField(
            model_name="product",
            name="image",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="introduction",
            field=models.TextField(blank=True, help_text="Text to describe the page"),
        ),
        migrations.AlterField(
            model_name="productvariant",
            name="product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="variants",
                to="shop.product",
            ),
        ),
    ]