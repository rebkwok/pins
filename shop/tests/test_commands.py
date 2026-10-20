from datetime import datetime, UTC
from decimal import Decimal
from io import StringIO

import pytest
from model_bakery import baker

from django.core.management import CommandError, call_command
from wagtail.images.models import Image
from wagtail.models import Collection, Page, Site

from ..models import CategoryPage, Product, ProductVariant, Sale, ShopPage
from .factories import CategoryPageFactory

from salesman.core.utils import get_salesman_model

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")


def test_clear_expired_baskets_command(freezer, basket):
    freezer.move_to("2024-01-01 10:00")
    basket.timeout = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    basket.save()
    freezer.move_to("2023-12-01 10:00")
    stale_basket = baker.make("shop.Basket")
    freezer.move_to("2024-01-01 10:00")

    out = StringIO()
    call_command("clear_expired_baskets", stdout=out)

    assert not basket.items.exists()
    assert not Basket.objects.filter(id=stale_basket.id).exists()
    assert out.getvalue().strip() == (
        "Cleared 1 expired basket(s); deleted 1 stale empty basket(s)"
    )


# seed_shop


@pytest.fixture
def seed_settings(settings, tmp_path):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path
    yield settings


def seed(*args):
    out = StringIO()
    call_command("seed_shop", *args, stdout=out)
    return out.getvalue()


def test_seed_shop(seed_settings):
    output = seed()
    shop_page = ShopPage.objects.get()
    assert shop_page.get_parent() == Site.objects.get(is_default_site=True).root_page
    categories = CategoryPage.objects.child_of(shop_page)
    assert [c.title for c in categories.order_by("index")] == [
        "Calendars & Cards",
        "Clothing",
        "Mugs & Gifts",
    ]
    assert Product.objects.count() == 7
    assert ProductVariant.objects.count() == 13
    collection = Collection.objects.get(name="Shop seed images")
    assert Image.objects.filter(collection=collection).count() == 7
    calendar = Product.objects.get(name="2027 Podenco Calendar")
    # the product's image, then its variants' images
    assert [image.image.title for image in calendar.images] == [
        "Calendar front",
        "Calendar inside",
        "Calendar pack",
    ]
    tshirt = Product.objects.get(name="PINS T-shirt")
    assert [image.image.title for image in tshirt.images] == ["T-shirt", "T-shirt back"]
    assert calendar.variants.get(variant_name="Single").base_price == Decimal("12.00")
    assert calendar.variants.get(variant_name="Pack of 3").base_price == Decimal("30.00")
    assert Product.objects.get(name="Notebook").out_of_stock()
    # a product that doesn't need shipping
    assert not Product.objects.get(name="Raffle ticket").requires_shipping
    assert Product.objects.get(name="Podenco mug").requires_shipping
    assert not Sale.objects.exists()
    assert output.startswith("Created 11:")
    assert "Skipped (already exist) 0" in output


def test_seed_shop_twice(seed_settings):
    seed()
    output = seed()
    assert ShopPage.objects.count() == 1
    assert CategoryPage.objects.count() == 3
    assert Product.objects.count() == 7
    assert ProductVariant.objects.count() == 13
    assert Image.objects.count() == 7
    assert output.startswith("Created 0: -")
    assert "Skipped (already exist) 11" in output


def test_seed_shop_doesnt_change_existing(seed_settings, product):
    # an existing shop page, category and product
    shop_page = product.category_page.get_parent().specific
    # an existing product with the same name as one of the seed products
    clothing = CategoryPageFactory(parent=shop_page, title="My clothing", slug="clothing")
    tshirt = baker.make(
        "shop.Product", category_page=clothing, name="PINS T-shirt", price=99
    )

    output = seed()

    assert ShopPage.objects.get() == shop_page
    assert "shop page 'Test page'" in output
    product.refresh_from_db()
    assert product.name == "Test Product"
    assert product.category_page.title == "Test Category"
    clothing.refresh_from_db()
    assert clothing.title == "My clothing"
    tshirt.refresh_from_db()
    assert tshirt.price == 99
    assert not tshirt.variants.exists()
    assert "product 'PINS T-shirt'" in output.split("Skipped")[1]
    # the other seed products are added to the existing shop
    assert Product.objects.count() == 8
    assert CategoryPage.objects.child_of(shop_page).count() == 4


def test_seed_shop_requires_debug(seed_settings):
    seed_settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG is off"):
        seed()
    assert not Product.objects.exists()
    seed("--force")
    assert Product.objects.count() == 7


def test_seed_shop_slug_conflict(seed_settings):
    root = Site.objects.get(is_default_site=True).root_page
    root.add_child(instance=Page(title="Shop", slug="shop"))
    with pytest.raises(CommandError, match="slug 'shop' already exists"):
        seed()


def test_seed_shop_sale(seed_settings):
    output = seed("--sale")
    sale = Sale.objects.get()
    assert Sale.current_sale() == sale
    assert sale.sale_products.get().product.name == "Podenco mug"
    assert "sale 'Seed sale' (20% off 'Podenco mug')" in output
    # not created again
    output = seed("--sale")
    assert Sale.objects.count() == 1
    assert "sale (a sale already exists for these dates)" in output


def test_seed_shop_sale_product_not_found(seed_settings, monkeypatch):
    monkeypatch.setattr(
        "shop.management.commands.seed_shop.SALE_PRODUCT", "No such product"
    )
    output = seed("--sale")
    assert not Sale.objects.exists()
    assert "sale ('No such product' not found)" in output
