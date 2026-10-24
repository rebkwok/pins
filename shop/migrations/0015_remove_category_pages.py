"""
Products and sale categories now use categories (see 0014): remove their
category page fields, and delete the category pages.
"""

import django.db.models.deletion
from django.db import migrations, models


def delete_category_pages(apps, schema_editor):
    Page = apps.get_model("wagtailcore", "Page")
    CategoryPage = apps.get_model("shop", "CategoryPage")
    pages = list(CategoryPage.objects.all())
    parent_paths = {page.path[: -4] for page in pages}
    # (0014 checked they have no child pages)
    Page.objects.filter(pk__in=[page.pk for page in pages]).delete()
    # Keep the page tree's child counts right
    for parent in Page.objects.filter(path__in=parent_paths):
        parent.numchild = Page.objects.filter(
            path__startswith=parent.path, depth=parent.depth + 1
        ).count()
        parent.save(update_fields=["numchild"])


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0014_category"),
    ]

    operations = [
        migrations.RemoveField(model_name="product", name="category_page"),
        migrations.AlterField(
            model_name="product",
            name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="products", to="shop.category"),
        ),
        migrations.AlterUniqueTogether(name="salecategory", unique_together=set()),
        migrations.RemoveField(model_name="salecategory", name="category"),
        migrations.RenameField(model_name="salecategory", old_name="category_new", new_name="category"),
        migrations.AlterField(
            model_name="salecategory",
            name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="shop.category"),
        ),
        migrations.AlterUniqueTogether(name="salecategory", unique_together={("sale", "category")}),
        migrations.RunPython(delete_category_pages, migrations.RunPython.noop),
    ]
