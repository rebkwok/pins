"""
Shipping rates and shop FAQs:
- a "Standard" shipping rate (the default), at the shop settings' shipping cost,
  which every product that needs shipping is given
- Shop admins can add, change and delete shipping rates and FAQs
- the first FAQs
"""

from decimal import Decimal

from django.contrib.auth.management import create_permissions
from django.db import migrations

SHOP_ADMINS = "Shop admins"

FAQS = [
    (
        "How much is delivery?",
        "<p>Delivery within the UK depends on what you order. Each product's page "
        "shows its delivery cost. If your order has items with different delivery "
        "costs, you only pay the highest one.</p>",
    ),
    (
        "Can I collect my order instead?",
        "<p>Yes, if you've arranged it with PINS first - please "
        '<a href="/contact-us/">contact us</a> before you order. Then choose '
        '"Collect in person" in your basket.</p>',
    ),
    (
        "Do you deliver outside the UK?",
        "<p>Our shop only delivers within the UK. If you're ordering from outside "
        'the UK, please <a href="/contact-us/">contact us</a> for shipping costs '
        "before you order.</p>",
    ),
    (
        "When will my order arrive?",
        "<p>Our shop is run by volunteers, who send out orders for us. We'll try "
        "to ship orders as soon as possible, but we can't guarantee delivery times.</p>"
        "<p>Some of our products are made to order, so they take longer to arrive. "
        "If a product is made to order, its page will say so.</p>"
    ),
    (
        "Why has only part of my order arrived?",
        "<p>Different products are sent by different volunteers, so an order with "
        "several products may arrive in more than one parcel.</p>",
    )
]


def add_rates_and_faqs(apps, schema_editor):
    ShopSettings = apps.get_model("shop", "ShopSettings")
    ShippingRate = apps.get_model("shop", "ShippingRate")
    Product = apps.get_model("shop", "Product")
    ShopFAQ = apps.get_model("shop", "ShopFAQ")

    settings = ShopSettings.objects.first()
    amount = settings.shipping_cost if settings is not None else Decimal("4.99")
    rate, _ = ShippingRate.objects.get_or_create(
        name="Standard", defaults={"amount": amount, "default": True}
    )
    Product.objects.filter(requires_shipping=True, shipping_rate=None).update(
        shipping_rate=rate
    )

    if not ShopFAQ.objects.exists():
        for sort_order, (question, answer) in enumerate(FAQS):
            ShopFAQ.objects.create(question=question, answer=answer, sort_order=sort_order)

    # Models' permissions are only created after all the migrations have run
    # (e.g. on a new database), so create them now
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group = Group.objects.filter(name=SHOP_ADMINS).first()
    if group is not None:
        group.permissions.add(
            *Permission.objects.filter(
                content_type__app_label="shop",
                codename__in=[
                    f"{action}_{model}"
                    for model in ["shippingrate", "shopfaq"]
                    for action in ["add", "change", "delete", "view"]
                ],
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0029_shipping_rates_and_faqs"),
    ]

    # (reversing leaves the rates and FAQs, which 0029's reversal removes)
    operations = [migrations.RunPython(add_rates_and_faqs, migrations.RunPython.noop)]
