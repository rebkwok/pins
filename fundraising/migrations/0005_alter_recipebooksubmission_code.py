# Generated by Django 5.0.1 on 2024-01-25 18:47

import fundraising.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fundraising', '0004_recipebooksubmission_category_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='recipebooksubmission',
            name='code',
            field=models.PositiveIntegerField(default=fundraising.models.get_random_code),
        ),
    ]
