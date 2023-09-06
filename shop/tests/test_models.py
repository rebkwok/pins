import pytest
from model_bakery import baker


pytestmark = pytest.mark.django_db


@pytest.fixture
def category():
    yield baker.make("shop.ProductCategory", name="Test Category")


@pytest.fixture
def product(category):
    yield baker.make("shop.Product", name="Test Product", category=category)


def test_category(category):
    assert str(category) == "Test Category"
    assert category.get_product_count() == "0 live (0 total)"
    assert list(category.live_products) == []


def test_product(product):
    assert str(product) == "Test Product"
    assert product.get_variant_count() == "0 live (0 total)"
    assert list(product.live_variants) == []
    assert product.identifier == "test-category-test-product"


def test_product_variant(product):
    variant = baker.make("shop.ProductVariant", product=product, name="Small", price=10)
    assert str(variant) == "Test Product - Small"
    assert variant.get_price(None) == 10
    assert variant.category == product.category
    assert variant.code == str(variant.id)


def test_live_products(category, product):
    # product is live
    assert product.live
    # but has no variants yet
    assert not product.variants.exists()
    # so category live product count is still 0
    assert category.live_products.count() == 0

    # make a not-live variant
    variant = baker.make(
        "shop.ProductVariant", product=product, name="Small", price=10, live=False
    )
    assert category.live_products.count() == 0
    assert product.variants.exists()
    assert product.live_variants.count() == 0

    # when the variant is live, the product is also properly live
    variant.live = True
    variant.save()
    assert product.live_variants.count() == 1
    assert category.live_products.count() == 1
