"""The import_shop_stock command: products from the old shop's CSV"""

import csv
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from model_bakery import baker

from ..management.commands.import_shop_stock import description_html, parse_variant
from ..models import DISPATCHERS_GROUP, Category, Product

pytestmark = pytest.mark.django_db

HEADER = [
    "Name", "Category", "Description", "Cost", "Variants", "Variants share stock",
    "Stock", "Items per pack", "Dispatcher",
]


def write_csv(tmp_path, rows):
    path = tmp_path / "stock.csv"
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return str(path)


def run(path, *args):
    out = StringIO()
    call_command("import_shop_stock", path, *args, stdout=out)
    return out.getvalue()


ROWS = [
    ["Recipe Book", "Books & Gifts", "A book.\n\nPlease note this order form is for shipping within the UK ONLY. If you are ordering from outside the UK, please contact us for shipping costs.", "15", "", "N", "15", "1", "becky"],
    ["Harness", "Dog accessories", "Size guide\n\nSmall\nNeck 12\"-17\"", "33.99", "S, Red", "N", "No limit", "1", "gail"],
    ["", "", "", "35.99", "M, Red", "N", "No limit", "1", "gail"],
    ["Hoodie", "Clothing", "See [the march](https://example.com/march).", "38", "White, XS", "N", "No limit", "1", "gail"],
    ["", "", "", "38", "XL", "N", "No limit", "1", "gail"],
    ["Cards", "Cards & Calendars", "Cards.", "4", "Single pack (4 cards)", "Y", "90", "1", ""],
    ["", "", "", "7", "Double pack (8 cards)", "Y", "90", "2", ""],
    ["Bottle Bags", "Books & Gifts", "Bags.", "6", "Penguins", "N", "3", "1", "becky"],
    ["", "", "", "6", "Christmas unicorns", "N", "0", "1", "becky"],
    ["", "", "", "", "", "", "", "", ""],
]


@pytest.fixture
def dispatchers():
    group = Group.objects.get(name=DISPATCHERS_GROUP)
    becky = baker.make("auth.User", username="becky", email="becky@test.com")
    becky.groups.add(group)
    # (not a dispatcher yet, and no email address)
    gail = baker.make("auth.User", username="gail", email="")
    return becky, gail


def test_import(tmp_path, dispatchers):
    becky, gail = dispatchers
    output = run(write_csv(tmp_path, ROWS))
    assert "5 product(s) imported, 0 skipped" in output
    # categories, in the CSV's order
    assert [category.title for category in Category.objects.all()] == [
        "Books & Gifts", "Dog accessories", "Clothing", "Cards & Calendars",
    ]
    # a product with one option
    book = Product.objects.get(name="Recipe Book")
    (variant,) = book.variants.all()
    assert (variant.variant_name, variant.colour, variant.size, variant.stock) == ("", "", "", 15)
    assert (book.price, book.dispatcher, book.notify_dispatcher) == (Decimal("15"), becky, True)
    # (the old UK shipping note is removed)
    assert book.description == "<p>A book.</p>"
    # sizes and colours, no stock limit, a different price
    harness = Product.objects.get(name="Harness")
    assert harness.unlimited_stock
    assert [(v.size, v.colour, v.price) for v in harness.variants.all()] == [
        ("S", "Red", None), ("M", "Red", Decimal("35.99")),
    ]
    assert harness.description == "<p>Size guide</p><p>Small<br/>Neck 12&quot;-17&quot;</p>"
    # gail: added to the Dispatchers group; no email address, so not emailed
    assert gail.groups.filter(name=DISPATCHERS_GROUP).exists()
    assert (harness.dispatcher, harness.notify_dispatcher) == (gail, False)
    assert "Added 'gail' to the Dispatchers group." in output
    assert "'Harness': gail has no email address" in output
    # colour then size; a size alone; a link
    hoodie = Product.objects.get(name="Hoodie")
    assert [(v.colour, v.size) for v in hoodie.variants.all()] == [("White", "XS"), ("", "XL")]
    assert hoodie.description == '<p>See <a href="https://example.com/march">the march</a>.</p>'
    # shared stock, in packs; no dispatcher
    cards = Product.objects.get(name="Cards")
    assert (cards.shares_stock, cards.stock, cards.dispatcher) == (True, 90, None)
    assert [(v.variant_name, v.pack_size, v.stock) for v in cards.variants.all()] == [
        ("Single pack (4 cards)", 1, 0), ("Double pack (8 cards)", 2, 0),
    ]
    # named variants, one out of stock
    bags = Product.objects.get(name="Bottle Bags")
    assert [(v.variant_name, v.stock) for v in bags.variants.all()] == [("Penguins", 3), ("Christmas unicorns", 0)]
    # everything is valid, as if saved in the admin (apart from gail's email)
    for product in Product.objects.exclude(dispatcher=gail):
        product.full_clean()
        for variant in product.variants.all():
            variant.full_clean()


def test_run_again_skips(tmp_path, dispatchers):
    path = write_csv(tmp_path, ROWS)
    run(path)
    output = run(path)
    assert "0 product(s) imported, 5 skipped" in output
    assert "Skipped 'Harness' (already in 'Dog accessories')." in output
    assert Product.objects.count() == 5


def test_existing_category(tmp_path, dispatchers):
    Category.objects.create(title="books & gifts")
    run(write_csv(tmp_path, ROWS))
    assert Category.objects.filter(title__iexact="books & gifts").count() == 1


def test_dry_run(tmp_path, dispatchers):
    output = run(write_csv(tmp_path, ROWS), "--dry-run")
    assert "Dry run (nothing saved): 5 product(s) imported" in output
    assert Product.objects.count() == 0
    assert not Category.objects.exists()


def test_missing_dispatchers(tmp_path):
    with pytest.raises(CommandError, match="No user for the dispatcher\\(s\\): becky, gail"):
        run(write_csv(tmp_path, ROWS))
    assert Product.objects.count() == 0


def test_create_dispatchers(tmp_path):
    output = run(write_csv(tmp_path, ROWS), "--create-dispatchers")
    assert "Created the user 'gail' (a dispatcher)." in output
    harness = Product.objects.get(name="Harness")
    assert harness.dispatcher.email == "gail@example.com"
    assert harness.notify_dispatcher


@pytest.mark.parametrize(
    "rows,error",
    [
        ([["", "", "", "5", "", "N", "1", "1", ""]], "Row 2: a variant without a product before it."),
        ([["Mug", "", "", "5", "", "N", "1", "1", ""]], "Row 2: 'Mug' has no category."),
        ([["Mug", "Gifts", "", "five", "", "N", "1", "1", ""]], "Row 2: the cost 'five' isn't a price."),
        ([["Mug", "Gifts", "", "-5", "", "N", "1", "1", ""]], "Row 2: the cost can't be negative."),
        ([["Mug", "Gifts", "", "5", "", "N", "lots", "1", ""]], "Row 2: Stock 'lots' isn't a number."),
        ([["Mug", "Gifts", "", "5", "", "N", "-1", "1", ""]], "Row 2: Stock can't be negative."),
        (
            [["Mug", "Gifts", "", "5", "Red", "N", "No limit", "1", ""], ["", "", "", "5", "Blue", "N", "2", "1", ""]],
            "'Mug' has variants with and without a stock limit",
        ),
        ([["Mug", "Gifts", "", "5", "", "Y", "No limit", "1", ""]], "'Mug' can't share stock and have no stock limit."),
        (
            [["Cards", "Gifts", "", "5", "Single", "Y", "10", "1", ""], ["", "", "", "9", "Double", "Y", "8", "2", ""]],
            "'Cards' shares stock, but its variants have different stock.",
        ),
        ([["Tee", "Clothing", "", "5", "M", "Y", "10", "1", ""]], "'Tee' shares stock, so its variants can't have colours or sizes."),
        ([["Cards", "Gifts", "", "5", "Pack", "N", "10", "5", ""]], "'Cards' has items per pack, but its variants don't share stock."),
    ],
)
def test_errors(tmp_path, rows, error):
    with pytest.raises(CommandError) as raised:
        run(write_csv(tmp_path, rows))
    assert error in str(raised.value)
    assert Product.objects.count() == 0


def test_no_file():
    with pytest.raises(CommandError, match="No such file: nope.csv"):
        run("nope.csv")


@pytest.mark.parametrize(
    "text,parsed",
    [
        ("", ("", "", "")),
        ("S, Red", ("", "Red", "S")),
        ("White, xs", ("", "White", "XS")),
        ("2XL", ("", "", "2XL")),
        ("Grey Cartoon Dogs", ("Grey Cartoon Dogs", "", "")),
        ("Men's, Black, M", ("Men's, Black, M", "", "")),
    ],
)
def test_parse_variant(text, parsed):
    assert parse_variant(text) == parsed


def test_description_html():
    assert description_html("One\r\ntwo\r\n\r\n<b>three</b>") == "<p>One<br/>two</p><p>&lt;b&gt;three&lt;/b&gt;</p>"
    assert description_html("") == ""


# --reset-stock: products that already exist get the CSV's stock again


def test_reset_stock(tmp_path, dispatchers):
    path = write_csv(tmp_path, ROWS)
    run(path)
    # (e.g. after testing: stock sold, settings changed, a variant added)
    bags = Product.objects.get(name="Bottle Bags")
    bags.variants.filter(variant_name="Penguins").update(stock=1)
    extra = baker.make("shop.ProductVariant", product=bags, variant_name="Robins", stock=5)
    cards = Product.objects.get(name="Cards")
    Product.objects.filter(pk=cards.pk).update(stock=12)
    harness = Product.objects.get(name="Harness")
    Product.objects.filter(pk=harness.pk).update(unlimited_stock=False, description="<p>Edited</p>")
    output = run(path, "--reset-stock")
    assert "0 product(s) imported, 5 with their stock reset." in output
    assert {v.variant_name: v.stock for v in bags.variants.all()} == {
        "Penguins": 3, "Christmas unicorns": 0, "Robins": 5,
    }
    assert "'Bottle Bags': the variant 'Robins' isn't in the CSV; its stock wasn't changed." in output
    assert "Reset the stock of 'Bottle Bags' (3, 0)." in output
    assert Product.objects.get(pk=cards.pk).stock == 90
    assert "Reset the stock of 'Cards' (shared stock 90)." in output
    harness.refresh_from_db()
    # (nothing else is changed)
    assert harness.unlimited_stock
    assert harness.description == "<p>Edited</p>"
    assert "Reset the stock of 'Harness' (no stock limit)." in output
    assert Product.objects.get(name="Bottle Bags").variants.get(pk=extra.pk).stock == 5


def test_reset_stock_missing_variant(tmp_path, dispatchers):
    path = write_csv(tmp_path, ROWS)
    run(path)
    Product.objects.get(name="Harness").variants.filter(size="M").delete()
    output = run(path, "--reset-stock")
    assert "'Harness': no variant 'Red, M' to reset the stock of" in output


def test_reset_stock_new_products_imported(tmp_path, dispatchers):
    output = run(write_csv(tmp_path, ROWS), "--reset-stock")
    assert "5 product(s) imported, 0 with their stock reset." in output
