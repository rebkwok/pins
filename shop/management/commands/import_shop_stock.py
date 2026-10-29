"""
Import the shop's products from a CSV file (the stock of the shop before this
one), e.g.

    python manage.py import_shop_stock pins_current_stock.csv

The CSV's columns: Name, Category, Description, Cost, Variants, Variants share
stock, Stock, Items per pack, Dispatcher. A row with a Name starts a product;
the rows after it with no Name are more of its variants. For each variant:

- Variants: e.g. "S, Red" or "White, XS" (a size, and a colour), "M" (a size),
  "Grey Cartoon Dogs" or "Single pack (4 cards)" (a name), or blank (the
  product's only option).
- Cost: the variant's price (the product's price is its first variant's; other
  variants with different prices have their own).
- Stock: a number, or "No limit" (the product has no stock limit). If the
  variants share stock ("Variants share stock" Y), it's the shared stock, in
  single items, and "Items per pack" is how many each variant uses.
- Dispatcher: the dispatcher's username (they're emailed about new orders for
  the product, if they have an email address). They must exist (or use
  --create-dispatchers, e.g. for testing, which gives them an @example.com
  address); they're added to the Dispatchers group if they're not in it.

Categories are created if they don't exist. Products that already exist (by
name, in their category) are skipped, so the command can be run again; with
--reset-stock, their stock is set to the CSV's instead (e.g. after testing the
shop): their variants' stock, shared stock, or no stock limit, with variants
matched by name, colour and size. (Nothing else about them is changed, and
their stock is set as it is in the CSV, whatever is in customers' baskets.)
Descriptions are plain text: blank lines separate paragraphs, and Markdown links
([text](url)) become links; the old "shipping within the UK ONLY" note is
removed (the shop shows it with the delivery option).
"""

import csv
import re
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.html import escape

from ...models import DISPATCHERS_GROUP, Category, Product, ProductVariant

NO_LIMIT = "no limit"
SIZES = {"XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL"}
UK_NOTE = "Please note this order form is for shipping within the UK ONLY"
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


class ImportError(CommandError):
    pass


def parse_variant(text):
    """
    A variant's (variant_name, colour, size) from the CSV's Variants text, e.g.
    "S, Red" -> ("", "Red", "S"), "White, XS" -> ("", "White", "XS"), "M" ->
    ("", "", "M"), "Grey Cartoon Dogs" -> ("Grey Cartoon Dogs", "", "")
    """
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return "", "", ""
    sizes = [part for part in parts if part.upper() in SIZES]
    others = [part for part in parts if part.upper() not in SIZES]
    if len(sizes) == 1 and len(others) <= 1:
        return "", (others[0] if others else ""), sizes[0].upper()
    return text.strip(), "", ""


def description_html(text):
    """The CSV's plain text description, as rich text (HTML)"""
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
        if paragraph.strip() and not paragraph.strip().startswith(UK_NOTE)
    ]
    html = []
    for paragraph in paragraphs:
        # escape first, then make the Markdown links into links
        escaped = escape(paragraph)
        linked = LINK.sub(lambda m: f'<a href="{m[2]}">{m[1]}</a>', escaped)
        html.append("<p>" + linked.replace("\n", "<br/>") + "</p>")
    return "".join(html)


def parse_price(value, row_number):
    try:
        price = Decimal(value.strip())
    except InvalidOperation:
        raise ImportError(f"Row {row_number}: the cost '{value}' isn't a price.")
    if price < 0:
        raise ImportError(f"Row {row_number}: the cost can't be negative.")
    return price


def parse_int(value, row_number, column):
    try:
        number = int(value.strip())
    except ValueError:
        raise ImportError(f"Row {row_number}: {column} '{value}' isn't a number.")
    if number < 0:
        raise ImportError(f"Row {row_number}: {column} can't be negative.")
    return number


def read_products(file):
    """
    The products in the CSV: [{"name", "category", "description", "shares_stock",
    "unlimited", "stock", "dispatcher", "variants": [{"row", "variant_name",
    "colour", "size", "price", "stock", "pack_size"}]}]
    """
    products = []
    # (row 1 is the header)
    for row_number, row in enumerate(csv.DictReader(file), start=2):
        if (row.get("Name") or "").strip():
            products.append(
                {
                    "row": row_number,
                    "name": row["Name"].strip(),
                    "category": (row.get("Category") or "").strip(),
                    "description": row.get("Description") or "",
                    "shares_stock": (row.get("Variants share stock") or "").strip().upper() == "Y",
                    "dispatcher": (row.get("Dispatcher") or "").strip(),
                    "variants": [],
                }
            )
        elif not products:
            raise ImportError(f"Row {row_number}: a variant without a product before it.")
        elif not any((value or "").strip() for value in row.values()):
            continue
        product = products[-1]
        variant_name, colour, size = parse_variant(row.get("Variants") or "")
        stock = (row.get("Stock") or "").strip()
        product["variants"].append(
            {
                "row": row_number,
                "variant_name": variant_name,
                "colour": colour,
                "size": size,
                "price": parse_price(row.get("Cost") or "", row_number),
                "stock": stock,
                "pack_size": parse_int(row.get("Items per pack") or "1", row_number, "Items per pack"),
            }
        )
    for product in products:
        check_product(product)
    return products


def check_product(product):
    name, row = product["name"], product["row"]
    if not product["category"]:
        raise ImportError(f"Row {row}: '{name}' has no category.")
    stocks = [variant["stock"] for variant in product["variants"]]
    unlimited = [stock.lower() == NO_LIMIT for stock in stocks]
    if any(unlimited) and not all(unlimited):
        raise ImportError(
            f"Row {row}: '{name}' has variants with and without a stock limit; "
            "the stock limit is set for the whole product."
        )
    product["unlimited"] = all(unlimited)
    if product["unlimited"] and product["shares_stock"]:
        raise ImportError(f"Row {row}: '{name}' can't share stock and have no stock limit.")
    if not product["unlimited"]:
        for variant in product["variants"]:
            variant["stock"] = parse_int(variant["stock"], variant["row"], "Stock")
    if product["shares_stock"]:
        shared = {variant["stock"] for variant in product["variants"]}
        if len(shared) > 1:
            raise ImportError(
                f"Row {row}: '{name}' shares stock, but its variants have different stock."
            )
        product["stock"] = shared.pop()
        if any(variant["colour"] or variant["size"] for variant in product["variants"]):
            raise ImportError(
                f"Row {row}: '{name}' shares stock, so its variants can't have colours or sizes."
            )
    else:
        product["stock"] = 0
        if any(variant["pack_size"] != 1 for variant in product["variants"]):
            raise ImportError(
                f"Row {row}: '{name}' has items per pack, but its variants don't share stock."
            )


class Command(BaseCommand):
    help = "Import the shop's products from a CSV file (see the module's docstring)"

    def add_arguments(self, parser):
        parser.add_argument("csv_file")
        parser.add_argument(
            "--create-dispatchers",
            action="store_true",
            help="Create dispatchers' users if they don't exist (e.g. for testing).",
        )
        parser.add_argument(
            "--reset-stock",
            action="store_true",
            help="Set the stock of products that already exist to the CSV's.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would be done, without saving."
        )

    def handle(
        self, csv_file, create_dispatchers=False, dry_run=False, reset_stock=False, **options
    ):
        try:
            with open(csv_file, newline="", encoding="utf-8-sig") as file:
                products = read_products(file)
        except FileNotFoundError:
            raise CommandError(f"No such file: {csv_file}")
        self.messages = []
        self.reset_stock = reset_stock
        with transaction.atomic():
            dispatchers = self.get_dispatchers(products, create_dispatchers)
            counts = {"imported": 0, "skipped": 0, "reset": 0}
            for product in products:
                counts[self.import_product(product, dispatchers)] += 1
            if dry_run:
                transaction.set_rollback(True)
        for message in self.messages:
            self.stdout.write(message)
        summary = f"{counts['imported']} product(s) imported, "
        if reset_stock:
            summary += f"{counts['reset']} with their stock reset."
        else:
            summary += f"{counts['skipped']} skipped (already in the shop)."
        if dry_run:
            summary = f"Dry run (nothing saved): {summary}"
        self.stdout.write(self.style.SUCCESS(summary))

    def get_dispatchers(self, products, create):
        """The dispatchers' users, by username, in the Dispatchers group"""
        User = get_user_model()
        group = Group.objects.get(name=DISPATCHERS_GROUP)
        usernames = sorted({product["dispatcher"] for product in products if product["dispatcher"]})
        users = {user.username: user for user in User.objects.filter(username__in=usernames)}
        missing = [username for username in usernames if username not in users]
        if missing and not create:
            raise CommandError(
                f"No user for the dispatcher(s): {', '.join(missing)}. Add them first "
                "(or use --create-dispatchers, e.g. for testing)."
            )
        for username in missing:
            users[username] = User.objects.create_user(
                username=username,
                first_name=username.capitalize(),
                email=f"{username}@example.com",
            )
            self.messages.append(f"Created the user '{username}' (a dispatcher).")
        for user in users.values():
            if not user.groups.filter(pk=group.pk).exists():
                user.groups.add(group)
                self.messages.append(f"Added '{user.username}' to the Dispatchers group.")
        return users

    def import_product(self, data, dispatchers):
        category = Category.objects.filter(title__iexact=data["category"]).first()
        if category is None:
            category = Category.objects.create(title=data["category"])
            self.messages.append(f"Created the category '{category.title}'.")
        existing = Product.objects.filter(category=category, name=data["name"]).first()
        if existing is not None:
            if self.reset_stock:
                self.reset_product_stock(existing, data)
                return "reset"
            self.messages.append(f"Skipped '{data['name']}' (already in '{category.title}').")
            return "skipped"
        variants = data["variants"]
        price = variants[0]["price"]
        dispatcher = dispatchers.get(data["dispatcher"])
        # (dispatchers can only be emailed if they have an email address)
        notify = dispatcher is not None and bool(dispatcher.email)
        if dispatcher is not None and not notify:
            self.messages.append(
                f"'{data['name']}': {dispatcher.username} has no email address, so isn't "
                "emailed about its orders (tick 'Email the dispatcher about new orders' "
                "once they have one)."
            )
        product = Product.objects.create(
            category=category,
            name=data["name"],
            description=description_html(data["description"]),
            price=price,
            unlimited_stock=data["unlimited"],
            shares_stock=data["shares_stock"],
            stock=data["stock"],
            dispatcher=dispatcher,
            notify_dispatcher=notify,
        )
        for sort_order, variant in enumerate(variants):
            ProductVariant.objects.create(
                product=product,
                sort_order=sort_order,
                variant_name=variant["variant_name"],
                colour=variant["colour"],
                size=variant["size"],
                price=variant["price"] if variant["price"] != price else None,
                stock=0 if data["unlimited"] or data["shares_stock"] else variant["stock"],
                pack_size=variant["pack_size"],
            )
        self.messages.append(
            f"Imported '{product.name}' ({len(variants)} variant(s)) into '{category.title}'."
        )
        return "imported"

    def reset_product_stock(self, product, data):
        """Set an existing product's stock to the CSV's (see the module's docstring)"""
        product.unlimited_stock = data["unlimited"]
        product.shares_stock = data["shares_stock"]
        product.stock = data["stock"]
        product.save(update_fields=["unlimited_stock", "shares_stock", "stock"])
        variants = {
            (variant.variant_name, variant.colour, variant.size): variant
            for variant in product.variants.all()
        }
        found = set()
        for row in data["variants"]:
            key = (row["variant_name"], row["colour"], row["size"])
            variant = variants.get(key)
            if variant is None:
                self.messages.append(
                    f"'{product.name}': no variant '{', '.join(part for part in key if part)}' "
                    "to reset the stock of (variants aren't added; add it in the admin)."
                )
                continue
            found.add(key)
            variant.stock = 0 if data["unlimited"] or data["shares_stock"] else row["stock"]
            if data["shares_stock"]:
                variant.pack_size = row["pack_size"]
            variant.save(update_fields=["stock", "pack_size"])
        for key in variants.keys() - found:
            self.messages.append(
                f"'{product.name}': the variant '{', '.join(part for part in key if part) or '(no name)'}' "
                "isn't in the CSV; its stock wasn't changed."
            )
        if data["unlimited"]:
            stock = "no stock limit"
        elif data["shares_stock"]:
            stock = f"shared stock {data['stock']}"
        else:
            stock = ", ".join(str(row["stock"]) for row in data["variants"])
        self.messages.append(f"Reset the stock of '{product.name}' ({stock}).")
