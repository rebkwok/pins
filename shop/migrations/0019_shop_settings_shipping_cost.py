"""
The shipping cost moves from the SHOP_SHIPPING_COST setting (an environment
variable) into the shop settings, so shop admins can change it: an existing
SHOP_SHIPPING_COST is copied in.
"""

import os

import django.core.validators
import wagtail.contrib.forms.models
from decimal import Decimal
from django.db import migrations, models


def copy_shipping_cost(apps, schema_editor):
    shipping_cost = os.environ.get("SHOP_SHIPPING_COST")
    if shipping_cost:
        ShopSettings = apps.get_model("shop", "ShopSettings")
        ShopSettings.objects.update(shipping_cost=Decimal(shipping_cost))


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0018_dispatcher_choices'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='shopsettings',
            options={'verbose_name': 'Shop settings'},
        ),
        migrations.AddField(
            model_name='shopsettings',
            name='shipping_cost',
            field=models.DecimalField(decimal_places=2, default=Decimal('4.99'), help_text='Added to orders that are delivered (not to orders that are collected, or have nothing that needs shipping).', max_digits=6, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AlterField(
            model_name='shopsettings',
            name='notify_email_addresses',
            field=models.CharField(blank=True, help_text='Every new order is emailed to these addresses (separate them with commas). Dispatchers are only emailed about products set to email them, so whoever gets these emails passes the rest on.', max_length=255, validators=[wagtail.contrib.forms.models.validate_to_address], verbose_name='Email new orders to'),
        ),
        migrations.AlterField(
            model_name='shopsettings',
            name='reply_to',
            field=models.EmailField(blank=True, help_text="Optional: where replies to the shop's emails (to customers and dispatchers) go.", max_length=255, verbose_name='Reply-to address'),
        ),
        migrations.RunPython(copy_shipping_cost, migrations.RunPython.noop),
    ]
