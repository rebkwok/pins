from datetime import datetime, timedelta
from datetime import timezone as datetime_tz
import pytest
from model_bakery import baker

from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone
from django.urls import reverse

from salesman.core.utils import get_salesman_model

from .factories import CategoryPageFactory
from ..models import Sale, SaleCategory, SaleProduct

pytestmark = pytest.mark.django_db

Basket = get_salesman_model("Basket")


def test_category(category_page):
    assert category_page.get_product_count() == "0 live (0 total)"
    assert list(category_page.live_products) == []


def test_shop_page(shop_page, category_page):
    assert category_page.live
    # not live category
    CategoryPageFactory(parent=shop_page, title="Test Category 1", live=False)
    assert shop_page.children().count() == 1


def test_shop_page_context(shop_page):
    # needs to create basket from request
    request = RequestFactory().get("/")
    shop_context = shop_page.get_context(request)
    assert shop_context["basket_quantity"] == 0


def test_product(product):
    assert str(product) == "Test Product"
    assert product.get_variant_count() == "0 live (0 total)"
    assert list(product.live_variants) == []
    assert product.identifier == "test-category-test-product"
    assert product.get_absolute_url() == reverse(
        "shop:product_detail", args=(product.id,)
    )


def test_product_variant(product):
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10
    )
    assert str(variant) == "Test Product - Small"
    assert variant.get_price(None) == 10
    assert variant.category_link() == product.category_link()
    assert variant.code == str(variant.id)


@pytest.mark.parametrize(
    "variant_name,colour,size,expected_str,expected_name_and_price",
    [
        (None, None, None, "Test Product", "£10"),
        ("Mug", None, None, "Test Product - Mug", "Mug - £10"),
        (None, "Green", None, "Test Product - Green", "Green - £10"),
        ("T-shirt", None, "S", "Test Product - T-shirt - S", "T-shirt - S - £10"),
        (
            "T-shirt",
            "Black",
            None,
            "Test Product - T-shirt - Black",
            "T-shirt - Black - £10",
        ),
        (
            "T-shirt",
            None,
            "One size",
            "Test Product - T-shirt - One size",
            "T-shirt - One size - £10",
        ),
        (
            "T-shirt",
            "Red",
            "M",
            "Test Product - T-shirt - Red, M",
            "T-shirt - Red, M - £10",
        ),
    ],
)
def test_product_variant_str(
    product, variant_name, colour, size, expected_str, expected_name_and_price
):
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name=variant_name, price=10
    )
    if colour:
        variant.colour = colour
        variant.save()
    if size:
        variant.size = size
        variant.save()

    assert str(variant) == variant.name == expected_str
    assert variant.name_and_price() == expected_name_and_price




@pytest.mark.parametrize(
    "variant_name,colour,size,expected_str,expected_name_and_price",
    [
        (None, None, None, "Test Product", "£8.00 (was £10)"),
        ("Mug", None, None, "Test Product - Mug", "Mug - £8.00 (was £10)"),
        (None, "Green", None, "Test Product - Green", "Green - £8.00 (was £10)"),
        ("T-shirt", None, "S", "Test Product - T-shirt - S", "T-shirt - S - £8.00 (was £10)"),
    ],
)
def test_product_variant_str_with_sale(
    freezer, sale_with_items, product, variant_name, colour, size, expected_str, expected_name_and_price
):  
    freezer.move_to("2022-01-01 09:00")
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name=variant_name, price=10
    )
    if colour:
        variant.colour = colour
        variant.save()
    if size:
        variant.size = size
        variant.save()

    assert str(variant) == variant.name == expected_str
    assert variant.name_and_price() == expected_name_and_price


def test_live_products(category_page, product):
    # product is live
    assert product.live
    # but has no variants yet
    assert not product.variants.exists()
    # so category live product count is still 0
    assert category_page.live_products.count() == 0

    # make a not-live variant
    variant = baker.make(
        "shop.ProductVariant",
        product=product,
        variant_name="Small",
        price=10,
        live=False,
    )
    assert category_page.live_products.count() == 0
    assert product.variants.exists()
    assert product.live_variants.count() == 0

    # when the variant is live, the product is also properly live
    variant.live = True
    variant.save()
    assert product.live_variants.count() == 1
    assert category_page.live_products.count() == 1


def test_product_out_of_stock(product):
    # 2 variants, one out of stock
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10, stock=5
    )
    baker.make(
        "shop.ProductVariant", product=product, variant_name="Medium", price=10, stock=0
    )

    assert not product.out_of_stock()

    variant.stock = 0
    variant.save()
    product.refresh_from_db()
    assert product.out_of_stock()


def test_product_out_of_stock_no_variants(product):
    assert not product.variants.exists()
    assert product.out_of_stock()


def test_product_images(product):
    # images are collated across product and product variants, duplicates are ignores
    image1 = baker.make("wagtailimages.Image")
    image2 = baker.make("wagtailimages.Image")
    product.image = image1
    product.save()
    baker.make(
        "shop.ProductVariant",
        product=product,
        variant_name="Small",
        price=10,
        image=image1,
    )
    baker.make(
        "shop.ProductVariant",
        product=product,
        variant_name="Medium",
        price=10,
        image=image2,
    )
    assert len(product.images) == 2


def test_basket_item(product):
    basket_item = baker.make("shop.BasketItem")
    assert basket_item.name == "(no name)"

    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10
    )
    basket_item.product = variant
    basket_item.quantity = 1
    basket_item.save()
    assert basket_item.name == "Test Product - Small"


def test_populate_order_from_basket(product):
    basket = baker.make(
        "shop.Basket", extra={"name": "Test user"}, shipping_method="collect"
    )
    variant = baker.make(
        "shop.ProductVariant", product=product, variant_name="Small", price=10
    )
    basket.add(product=variant, quantity=2)
    order = baker.make("shop.Order")

    order.populate_from_basket(basket=basket, request=None)
    assert order.items.count() == 1
    assert order.shipping_method == "collect"
    assert order.name == "Test user"


def test_basket_timeout(basket, freezer):
    # initial timeout is in future
    assert basket.timeout > timezone.now()
    # clearing basked has no effect
    Basket.clear_expired()
    assert basket.items.exists()

    # move time to more than 15 mins in future
    freezer.move_to(timezone.now() + timedelta(minutes=20))
    Basket.clear_expired()
    assert not basket.items.exists()


def test_current_sale_no_sale_items(freezer):
    sale = baker.make(
        Sale,
        start_date=datetime(2020, 2, 3, 10, 0, tzinfo=datetime_tz.utc),
        end_date=datetime(2020, 5, 2, 10, 0, tzinfo=datetime_tz.utc),
    )
    freezer.move_to("2020-04-03")
    assert Sale.current_sale() is None


@pytest.mark.parametrize(
    "current_time,is_current",
    [
        ("2020-01-03", False),
        ("2020-05-02 10:05", False),
        ("2020-04-03", True),
    ],
)
def test_current_sale(freezer, sale_with_items, current_time, is_current):
    sale_with_items.start_date = datetime(2020, 2, 3, 10, 0, tzinfo=datetime_tz.utc)
    sale_with_items.end_date = datetime(2020, 5, 2, 10, 0, tzinfo=datetime_tz.utc)
    sale_with_items.save()
    freezer.move_to(current_time)
    assert (Sale.current_sale() == sale_with_items) == is_current


@pytest.mark.parametrize(
    "sale_start,sale_end",
    [
        # overlaps start only
        (
            datetime(2020, 1, 3, 10, 0, tzinfo=datetime_tz.utc),
            datetime(2020, 2, 3, 10, 5, tzinfo=datetime_tz.utc),
        ),
        # overlaps end only
        (
            datetime(2020, 4, 3, 10, 0, tzinfo=datetime_tz.utc),
            datetime(2020, 5, 5, tzinfo=datetime_tz.utc),
        ),
        # overlaps both
        (
            datetime(2020, 1, 3, 10, 0, tzinfo=datetime_tz.utc),
            datetime(2020, 5, 5, tzinfo=datetime_tz.utc),
        ),
        # contained within
        (
            datetime(2020, 4, 1, 10, 0, tzinfo=datetime_tz.utc),
            datetime(2020, 4, 30, 10, tzinfo=datetime_tz.utc),
        ),
    ],
)
def test_cannot_create_sales_with_overlapping_dates(
    sale_with_items, sale_start, sale_end
):
    sale_with_items.start_date = datetime(2020, 2, 3, 10, 0, tzinfo=datetime_tz.utc)
    sale_with_items.end_date = datetime(2020, 5, 2, 10, 0, tzinfo=datetime_tz.utc)
    sale_with_items.save()
    with pytest.raises(ValidationError):
        baker.make(Sale, start_date=sale_start, end_date=sale_end)


def test_sale_str(sale_with_items):
    assert str(sale_with_items) == "Test Sale (01Jan22 - 02Jan22)"


def test_get_sale_item_for_product_variant(freezer, sale_with_items):
    # make sure sale is current
    freezer.move_to("2022-01-01 09:00")
    assert Sale.current_sale() == sale_with_items
    # product and its category are in the sale. All product non-sale price is £12
    # product = 20%; category = 10%
    # product takes precedence over category

    # make another product without its own SaleProduct discount; this inherits the SaleCategory

    product = sale_with_items.sale_products.first().product

    product_inheriting_discount = baker.make(
        "shop.Product",
        name="Another Product",
        category_page=product.category_page,
        price=12,
    )
    # make another product without its own SaleProduct discount; this is excluded from the sale
    product_excluded_from_sale = baker.make(
        "shop.Product",
        name="Non-sale Product",
        category_page=product.category_page,
        price=12,
    )
    SaleProduct.objects.create(
        sale=sale_with_items, product=product_excluded_from_sale, discount=0
    )

    # make a variant for each
    p_variant = baker.make("shop.ProductVariant", product=product)
    p_inheriting_variant = baker.make(
        "shop.ProductVariant", product=product_inheriting_discount
    )
    p_excluded = baker.make("shop.ProductVariant", product=product_excluded_from_sale)

    assert p_variant.get_sale_item().discount == 20
    assert p_inheriting_variant.get_sale_item().discount == 10
    assert p_excluded.get_sale_item() is None
