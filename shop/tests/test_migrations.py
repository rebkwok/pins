"""Data migrations"""
import pytest
import wagtail_factories
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from model_bakery import baker

BEFORE = [("shop", "0006_shipping_method_default_delivery")]
AFTER = [("shop", "0007_product_images")]


def migrate(targets):
    """Migrate to targets, returning the historical models"""
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_product_images_migration(category_page):
    image = wagtail_factories.ImageFactory()
    with_image = baker.make("shop.Product", category_page=category_page, name="Mug")
    without_image = baker.make("shop.Product", category_page=category_page, name="Card")
    baker.make("shop.ProductImage", product=with_image, image=image, sort_order=0)
    baker.make(
        "shop.ProductImage",
        product=with_image,
        image=wagtail_factories.ImageFactory(),
        sort_order=1,
    )
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        # backwards: the first product image becomes the product's image
        apps = migrate(BEFORE)
        Product = apps.get_model("shop", "Product")
        assert Product.objects.get(id=with_image.id).image_id == image.id
        assert Product.objects.get(id=without_image.id).image_id is None

        # forwards: the product's image becomes its first product image
        apps = migrate(AFTER)
        ProductImage = apps.get_model("shop", "ProductImage")
        assert list(
            ProductImage.objects.values_list("product_id", "image_id", "sort_order")
        ) == [(with_image.id, image.id, 0)]
    finally:
        migrate(leaf_nodes)
