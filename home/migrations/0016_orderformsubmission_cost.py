# Generated by Django 5.0.1 on 2024-01-26 14:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0015_orderformsubmission_reference_ordervoucher'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderformsubmission',
            name='cost',
            field=models.DecimalField(decimal_places=2, max_digits=10, null=True),
        ),
    ]
