# Generated by Django 4.2.3 on 2023-09-30 10:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("wagtailimages", "0025_alter_image_file_alter_rendition_file"),
        ("home", "0008_homepage_featured_section_body"),
    ]

    operations = [
        migrations.AddField(
            model_name="homepage",
            name="page_link_1_image",
            field=models.ForeignKey(
                blank=True,
                help_text="Background image",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
        migrations.AddField(
            model_name="homepage",
            name="page_link_2_image",
            field=models.ForeignKey(
                blank=True,
                help_text="Background image",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
    ]