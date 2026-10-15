import json
from datetime import datetime, timedelta
from datetime import timezone as datetime_tz
from decimal import Decimal

import pytest
from model_bakery import baker

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse
from wagtail.admin.panels import get_edit_handler

from salesman.core.utils import get_salesman_model

from .factories import CategoryPageFactory, ShopPageFactory
from ..models import CategoryPage, Product, Sale, SaleCategory, SaleProduct

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
        "shop.ProductVariant", product=product, variant_name=variant_name or "", price=10
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
        "shop.ProductVariant", product=product, variant_name=variant_name or "", price=10
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

    # move time to more than 30 mins in future
    freezer.move_to(timezone.now() + timedelta(minutes=35))
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


def test_basket_clear_expired(freezer, basket):
    freezer.move_to("2024-01-01 10:00")
    variant = basket.items.first().product
    assert variant.stock == 3
    not_expired = baker.make(
        "shop.Basket", timeout=datetime(2024, 1, 1, 11, 0, tzinfo=datetime_tz.utc)
    )
    not_expired.add(variant, quantity=1)
    basket.timeout = datetime(2024, 1, 1, 9, 0, tzinfo=datetime_tz.utc)
    basket.save()

    assert Basket.clear_expired() == 1
    assert not basket.items.exists()
    assert not_expired.items.exists()
    # items returned to stock
    variant.refresh_from_db()
    assert variant.stock == 4
    # timeout is reset so the basket isn't processed again
    basket.refresh_from_db()
    assert basket.timeout is None
    assert Basket.clear_expired() == 0


def test_basket_clear_expired_ignores_empty_baskets(freezer):
    freezer.move_to("2024-01-01 10:00")
    baker.make("shop.Basket", timeout=datetime(2024, 1, 1, 9, 0, tzinfo=datetime_tz.utc))
    assert Basket.clear_expired() == 0


def test_basket_delete_stale(freezer, basket):
    freezer.move_to("2024-01-01 10:00")
    old_empty = baker.make("shop.Basket")
    old_with_items = basket
    # an order has been created from this basket
    old_ordered = baker.make("shop.Basket", extra={"basket_id": 1234})
    Basket.objects.filter(
        id__in=[old_empty.id, old_with_items.id, old_ordered.id]
    ).update(date_updated=datetime(2023, 12, 1, tzinfo=datetime_tz.utc))
    recent_empty = baker.make("shop.Basket")

    assert Basket.delete_stale(days=7) == 1
    assert set(Basket.objects.values_list("id", flat=True)) == {
        old_with_items.id,
        old_ordered.id,
        recent_empty.id,
    }


@pytest.mark.parametrize("user_basket_timeout", [None, "cleared"])
def test_basket_merge_sets_timeout(freezer, settings, basket, user_basket_timeout):
    # A user basket that is new (no timeout) or has been cleared by
    # clear_expired (timeout reset to None) has items merged in
    freezer.move_to("2024-01-01 10:00")
    settings.BASKET_TIMEOUT_MINUTES = 30
    user_basket = baker.make("shop.Basket", user=baker.make("auth.User"))
    if user_basket_timeout == "cleared":
        user_basket.add(basket.items.first().product, quantity=1)
        user_basket.timeout = datetime(2024, 1, 1, 9, 0, tzinfo=datetime_tz.utc)
        user_basket.save()
        Basket.clear_expired()
        user_basket.refresh_from_db()
    assert user_basket.timeout is None

    user_basket.merge(basket)
    user_basket.refresh_from_db()
    assert user_basket.quantity == 2
    assert user_basket.timeout == datetime(2024, 1, 1, 10, 30, tzinfo=datetime_tz.utc)

    # merged items expire
    freezer.move_to("2024-01-01 10:31")
    assert Basket.clear_expired() == 1
    assert not user_basket.items.exists()


def test_basket_merge_empty_basket_does_not_set_timeout(basket):
    user_basket = baker.make("shop.Basket", user=baker.make("auth.User"))
    basket.clear()
    user_basket.merge(basket)
    user_basket.refresh_from_db()
    assert user_basket.timeout is None


# Out of stock


def test_product_out_of_stock_ignores_variants_not_live(product):
    # Live variants have no stock; a variant that isn't live has stock but
    # can't be added to the basket
    baker.make("shop.ProductVariant", product=product, variant_name="S", stock=0)
    baker.make("shop.ProductVariant", product=product, variant_name="M", stock=0)
    hidden = baker.make(
        "shop.ProductVariant", product=product, variant_name="L", stock=5, live=False
    )
    assert product.out_of_stock()
    hidden.live = True
    hidden.save()
    assert not product.out_of_stock()


def test_product_out_of_stock_negative_stock(product):
    # Negative stock on one variant doesn't cancel out another's stock
    baker.make("shop.ProductVariant", product=product, variant_name="S", stock=-2)
    baker.make("shop.ProductVariant", product=product, variant_name="M", stock=1)
    assert not product.out_of_stock()


def test_product_card_out_of_stock_ignores_variants_not_live(rf, product):
    baker.make("shop.ProductVariant", product=product, variant_name="S", stock=0)
    baker.make(
        "shop.ProductVariant", product=product, variant_name="L", stock=5, live=False
    )
    html = render_to_string(
        "shop/includes/product-listing-card.html", {"product": product}, rf.get("/")
    )
    assert "Out of stock" in html
    assert f"change_quantity_wrapper_{product.id}" not in html
    assert "Add to basket" not in html


# Variant uniqueness


@pytest.mark.parametrize(
    "fields",
    [
        {"variant_name": "Mug"},
        {"colour": "Green", "size": "M"},
        # all blank
        {},
    ],
)
def test_product_variant_unique_per_product(product, fields):
    baker.make("shop.ProductVariant", product=product, **fields)
    duplicate = baker.prepare("shop.ProductVariant", product=product, **fields)
    with pytest.raises(ValidationError, match="already has a variant"):
        duplicate.full_clean()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            duplicate.save()


def test_product_variant_same_options_on_other_products(product, category_page):
    other_product = baker.make("shop.Product", category_page=category_page)
    fields = {"variant_name": "Men's", "colour": "Black", "size": "M"}
    baker.make("shop.ProductVariant", product=product, **fields)
    variant = baker.prepare("shop.ProductVariant", product=other_product, **fields)
    variant.full_clean()
    variant.save()


def test_product_admin_form_rejects_duplicate_variants(product):
    # Duplicate variants added in the product's admin form (InlinePanel)
    form_class = get_edit_handler(Product).get_form_class()
    data = {
        "category_page": product.category_page.id,
        "name": "Mug",
        "price": "10",
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "index": "1",
        "live": "on",
        "variants-TOTAL_FORMS": "2",
        "variants-INITIAL_FORMS": "0",
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
    }
    for i in range(2):
        data.update(
            {
                f"variants-{i}-variant_name": "Large",
                f"variants-{i}-colour": "",
                f"variants-{i}-size": "",
                f"variants-{i}-stock": "1",
                f"variants-{i}-live": "on",
                f"variants-{i}-ORDER": str(i + 1),
            }
        )
    form = form_class(data, instance=Product(category_page=product.category_page))
    assert not form.is_valid()
    errors = form.formsets["variants"].non_form_errors()
    assert errors == [
        "Please correct the duplicate data for product, variant_name, colour and size, "
        "which must be unique."
    ]

    # the same form with different variants is valid
    data["variants-1-variant_name"] = "Small"
    form = form_class(data, instance=Product(category_page=product.category_page))
    assert form.is_valid(), form.errors


def test_product_variants_ordered_by_sort_order(product):
    second = baker.make("shop.ProductVariant", product=product, variant_name="B", sort_order=2)
    first = baker.make("shop.ProductVariant", product=product, variant_name="A", sort_order=1)
    assert list(product.variants.all()) == [first, second]


# Default price


def test_product_variant_base_price(product):
    # product price is 12
    variant = baker.make("shop.ProductVariant", product=product, price=None)
    assert variant.price is None
    assert variant.base_price == 12
    assert variant.get_price(None) == 12
    assert variant.name_and_price() == "£12"

    # a variant with no price follows changes to the product price
    product.price = 15
    product.save()
    variant.refresh_from_db()
    assert variant.base_price == 15

    variant.price = 9
    assert variant.base_price == 9


def test_product_variant_base_price_in_basket(product):
    variant = baker.make("shop.ProductVariant", product=product, price=None, stock=5)
    basket = baker.make("shop.Basket")
    basket.add(variant, quantity=2)
    basket.update(request=None)
    assert basket.total == 24


def test_product_variant_base_price_with_sale(freezer, sale_with_items, product):
    # product discount is 20%
    freezer.move_to("2022-01-01 09:00")
    variant = baker.make("shop.ProductVariant", product=product, price=None)
    assert variant.get_discounted_price() == Decimal("9.60")
    assert variant.name_and_price() == "£9.60 (was £12)"


# Sale dates


def test_edit_sale_without_changing_dates(sale_with_items):
    # previously, editing a sale found itself as an overlapping sale
    sale_with_items.name = "New name"
    sale_with_items.full_clean()
    sale_with_items.save()


def test_edit_sale_to_overlap_another(sale_with_items):
    other_sale = baker.make(
        Sale,
        start_date=datetime(2022, 2, 1, tzinfo=datetime_tz.utc),
        end_date=datetime(2022, 2, 5, tzinfo=datetime_tz.utc),
    )
    other_sale.start_date = datetime(2022, 1, 1, 12, tzinfo=datetime_tz.utc)
    with pytest.raises(ValidationError, match="A sale already exists"):
        other_sale.full_clean()


def test_sale_can_start_when_another_ends(sale_with_items):
    # sale_with_items ends at 2022-01-02 00:00
    sale = baker.make(
        Sale,
        start_date=sale_with_items.end_date,
        end_date=datetime(2022, 1, 5, tzinfo=datetime_tz.utc),
    )
    assert sale.id


def test_sale_clean_missing_dates():
    # e.g. invalid dates in the admin form, which reports those errors itself
    Sale(name="Sale").clean()


# Shop and category pages


def test_shop_page_categories_only_its_own(shop_page, category_page, home_page):
    other_shop = ShopPageFactory(parent=home_page, title="Other shop", slug="other")
    CategoryPageFactory(parent=other_shop, title="Other category")
    assert list(shop_page.categories()) == [category_page]


def test_category_page_cannot_have_category_children(category_page):
    assert not CategoryPage.can_create_at(category_page)


def test_category_link_escapes_title(product):
    product.category_page.title = "Mugs & <cups>"
    product.category_page.save()
    link = product.category_link()
    edit_url = reverse("wagtailadmin_pages:edit", args=(product.category_page.id,))
    assert f'href="{edit_url}"' in link
    assert "Mugs &amp; &lt;cups&gt;" in link
    variant = baker.make("shop.ProductVariant", product=product)
    assert variant.category_link() == link
