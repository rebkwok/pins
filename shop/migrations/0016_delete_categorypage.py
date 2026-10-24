from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0015_remove_category_pages"),
    ]

    operations = [
        migrations.DeleteModel(name="CategoryPage"),
    ]
