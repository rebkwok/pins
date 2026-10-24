"""
Categories become plain models (not Wagtail pages): copy the category pages
into categories, and point products and sale categories at them. The category
pages are removed in 0015.
"""

import django.db.models.deletion
import django.db.models.functions.text
import wagtail.fields
from django.db import migrations, models


def unique_value(value, taken, separator):
    """value, or value with a number added if it's taken"""
    candidate, number = value, 2
    while candidate.lower() in taken:
        candidate = f"{value}{separator}{number}"
        number += 1
    taken.add(candidate.lower())
    return candidate


def copy_categories(apps, schema_editor):
    Page = apps.get_model("wagtailcore", "Page")
    CategoryPage = apps.get_model("shop", "CategoryPage")
    Category = apps.get_model("shop", "Category")
    Product = apps.get_model("shop", "Product")
    SaleCategory = apps.get_model("shop", "SaleCategory")

    category_pages = list(CategoryPage.objects.order_by("index", "path"))
    with_children = [
        page.title
        for page in category_pages
        if Page.objects.filter(path__startswith=page.path, depth__gt=page.depth).exists()
    ]
    if with_children:
        raise RuntimeError(
            "These category pages have child pages, which would be deleted: "
            f"{', '.join(with_children)}. Move the child pages (e.g. under the shop "
            "page) before migrating."
        )
    titles, slugs = set(), set()
    for sort_order, page in enumerate(category_pages):
        category = Category.objects.create(
            # (titles had to be unique within each shop page; slugs within
            # their parent page)
            title=unique_value(page.title, titles, " "),
            slug=unique_value(page.slug, slugs, "-"),
            description=page.body,
            sort_order=sort_order,
        )
        Product.objects.filter(category_page_id=page.pk).update(category=category)
        SaleCategory.objects.filter(category_id=page.pk).update(category_new=category)


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0013_item_not_sent_status"),
        ("wagtailcore", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(help_text="Shown on the shop page, and as the category's page title.", max_length=255)),
                ("slug", models.SlugField(blank=True, help_text="The end of the category page's web address, e.g. 'clothing' for /shop/clothing/. Made from the title if left blank.", max_length=255, unique=True, verbose_name="Web address")),
                ("description", wagtail.fields.RichTextField(blank=True, help_text="Optional text shown at the top of the category's page.")),
                ("sort_order", models.IntegerField(blank=True, editable=False, null=True)),
            ],
            options={
                "verbose_name_plural": "categories",
                "ordering": ["sort_order", "title"],
                "constraints": [models.UniqueConstraint(django.db.models.functions.text.Lower("title"), name="unique_category_title")],
            },
        ),
        migrations.AddField(
            model_name="product",
            name="category",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="products", to="shop.category"),
        ),
        migrations.AddField(
            model_name="salecategory",
            name="category_new",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="shop.category"),
        ),
        migrations.RunPython(copy_categories, migrations.RunPython.noop),
    ]
