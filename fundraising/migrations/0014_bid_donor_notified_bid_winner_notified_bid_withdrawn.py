# Generated by Django 5.1 on 2024-10-20 13:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fundraising", "0013_alter_auction_options_alter_auctionitem_postage"),
    ]

    operations = [
        migrations.AddField(
            model_name="bid",
            name="donor_notified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="bid",
            name="winner_notified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="bid",
            name="withdrawn",
            field=models.BooleanField(default=False),
        ),
    ]
