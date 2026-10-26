from django.db import migrations


class Migration(migrations.Migration):
    """The shipping cost is now the products' shipping rates (see 0030)"""

    dependencies = [
        ("shop", "0030_shipping_rates_and_faqs_data"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="shopsettings",
            name="shipping_cost",
        ),
    ]
