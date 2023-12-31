# Generated by Django 4.2.3 on 2023-10-17 08:48

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("wagtailimages", "0025_alter_image_file_alter_rendition_file"),
        ("home", "0009_homepage_page_link_1_image_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderformpage",
            name="inline_image",
            field=models.ForeignKey(
                blank=True,
                help_text="Displayed before the body",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
        migrations.AddField(
            model_name="standardpage",
            name="inline_image",
            field=models.ForeignKey(
                blank=True,
                help_text="Displayed afer the introduction",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
        migrations.AlterField(
            model_name="orderformpage",
            name="image",
            field=models.ForeignKey(
                blank=True,
                help_text="Used for the hero image",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
        migrations.AlterField(
            model_name="standardpage",
            name="image",
            field=models.ForeignKey(
                blank=True,
                help_text="Displayed as the hero image. Landscape mode only; horizontal width between 1000px and 3000px.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
    ]
