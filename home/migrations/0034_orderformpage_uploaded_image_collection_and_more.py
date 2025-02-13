# Generated by Django 5.1 on 2024-10-24 07:58

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0033_adventcalendarpage_adventcalendarday"),
        ("wagtailcore", "0094_alter_page_locale"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderformpage",
            name="uploaded_image_collection",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="wagtailcore.collection",
            ),
        ),
        migrations.AlterField(
            model_name="orderformfield",
            name="field_type",
            field=models.CharField(
                choices=[
                    ("singleline", "Single line text"),
                    ("multiline", "Multi-line text"),
                    ("email", "Email"),
                    ("number", "Number"),
                    ("url", "URL"),
                    ("checkbox", "Checkbox"),
                    ("checkboxes", "Checkboxes"),
                    ("dropdown", "Drop down"),
                    ("multiselect", "Multiple select"),
                    ("radio", "Radio buttons"),
                    ("date", "Date"),
                    ("datetime", "Date/time"),
                    ("hidden", "Hidden field"),
                    ("image", "Upload Image"),
                ],
                max_length=16,
                verbose_name="field type",
            ),
        ),
    ]
