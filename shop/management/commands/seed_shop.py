import io
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.images import ImageFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont
from wagtail.images.models import Image
from wagtail.models import Collection, Site

from shop.models import (
    Category,
    Product,
    ProductImage,
    ProductVariant,
    Sale,
    SaleProduct,
    ShopPage,
)

IMAGE_COLLECTION = "Shop seed images"

# Categories, in display order, with their products. Each product has its images
# (title, colour and optional size of a generated image) and variants, which can
# also have images.
SHOP_DATA = [
    {
        "title": "Calendars & Cards",
        "slug": "calendars-cards",
        "products": [
            {
                "name": "2027 Podenco Calendar",
                "price": "12.00",
                "description": "A4 wall calendar with a podenco for every month.",
                "images": [("Calendar front", "#b5543f")],
                # Singles and packs of 3 are sold from the same 25 calendars
                "shares_stock": True,
                "stock": 25,
                "variants": [
                    {
                        "variant_name": "Single",
                        "stock": 0,
                        "image": ("Calendar inside", "#3f6fb5"),
                    },
                    {
                        "variant_name": "Pack of 3",
                        "price": "30.00",
                        "stock": 0,
                        "pack_size": 3,
                        "image": ("Calendar pack", "#3fb56f"),
                    },
                ],
            },
            {
                "name": "Christmas cards (pack of 10)",
                "price": "8.50",
                "description": "Ten cards with envelopes.",
                "variants": [{"stock": 40}],
            },
            {
                "name": "Notebook",
                "price": "5.00",
                "description": "A5 notebook (out of stock).",
                "variants": [{"stock": 0}],
            },
        ],
    },
    {
        "title": "Clothing",
        "slug": "clothing",
        "products": [
            {
                "name": "PINS T-shirt",
                "price": "18.00",
                "description": "Organic cotton T-shirt with the PINS logo.",
                "images": [("T-shirt", "#333333", (900, 600)), ("T-shirt back", "#555555")],
                "variants": [
                    *[{"colour": "Black", "size": size, "stock": 3} for size in ["S", "M", "L", "XL"]],
                    {"colour": "White", "size": "M", "stock": 0},
                ],
            },
            {
                "name": "PINS hoodie (unisex, organic cotton)",
                "price": "32.00",
                "description": "Warm hoodie.",
                "images": [("Hoodie black", "#111111")],
                "variants": [
                    {
                        "variant_name": "Men's",
                        "colour": "Black",
                        "size": "M",
                        "stock": 2,
                        "image": ("Hoodie black", "#111111"),
                    },
                    {
                        "variant_name": "Women's",
                        "colour": "Grey",
                        "size": "S",
                        "stock": 2,
                        "image": ("Hoodie grey", "#888888"),
                    },
                ],
            },
        ],
    },
    {
        "title": "Mugs & Gifts",
        "slug": "mugs-gifts",
        "products": [
            {
                "name": "Podenco mug",
                "price": "9.99",
                "description": "Dishwasher safe.",
                "variants": [{"stock": 12}],
            },
            {
                "name": "Raffle ticket",
                "price": "2.00",
                "description": "Entry into the PINS raffle; nothing is posted.",
                "requires_shipping": False,
                "variants": [{"stock": 100}],
            },
        ],
    },
]

SALE_CATEGORY = "mugs-gifts"
SALE_PRODUCT = "Podenco mug"


class Command(BaseCommand):
    help = (
        "Seed a shop with categories and products for local development. "
        "Anything that already exists is skipped; existing pages and products "
        "aren't changed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sale",
            action="store_true",
            help=f"Also create a current sale on '{SALE_PRODUCT}' (if no sale overlaps)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even if DEBUG is off",
        )

    def handle(self, sale, force, **kwargs):
        if not settings.DEBUG and not force:
            raise CommandError(
                "seed_shop is for local development; DEBUG is off (use --force to run anyway)"
            )
        self.created = []
        self.skipped = []
        with transaction.atomic():
            shop_page = self.get_shop_page()
            for index, category_data in enumerate(SHOP_DATA):
                category = self.get_category(category_data, index)
                for product_data in category_data["products"]:
                    self.create_product(category, product_data)
            if sale:
                self.create_sale()
        self.stdout.write(
            f"Created {len(self.created)}: {', '.join(self.created) or '-'}\n"
            f"Skipped (already exist) {len(self.skipped)}: {', '.join(self.skipped) or '-'}"
        )

    def get_shop_page(self):
        shop_page = ShopPage.objects.first()
        if shop_page is not None:
            self.skipped.append(f"shop page '{shop_page.title}'")
            return shop_page
        root = Site.objects.get(is_default_site=True).root_page
        if root.get_children().filter(slug="shop").exists():
            raise CommandError(
                "A page with the slug 'shop' already exists under the site root "
                "and isn't a shop page"
            )
        shop_page = root.add_child(
            instance=ShopPage(
                title="Shop",
                slug="shop",
                introduction=(
                    "All proceeds go to helping podencos in need. Thank you for "
                    "your support!"
                ),
            )
        )
        self.created.append("shop page 'Shop'")
        return shop_page

    def get_category(self, data, index):
        # An existing category with the slug or title (e.g. one created in the
        # admin with a different slug)
        category = Category.objects.filter(
            Q(slug=data["slug"]) | Q(title__iexact=data["title"])
        ).first()
        if category is not None:
            self.skipped.append(f"category '{category.title}'")
            return category
        category = Category.objects.create(
            title=data["title"], slug=data["slug"], sort_order=index
        )
        self.created.append(f"category '{category.title}'")
        return category

    def create_product(self, category, data):
        if Product.objects.filter(category=category, name=data["name"]).exists():
            self.skipped.append(f"product '{data['name']}'")
            return
        product = Product.objects.create(
            category=category,
            name=data["name"],
            price=Decimal(data["price"]),
            description=f"<p>{data['description']}</p>",
            requires_shipping=data.get("requires_shipping", True),
            shares_stock=data.get("shares_stock", False),
            stock=data.get("stock", 0),
        )
        for sort_order, image in enumerate(data.get("images", [])):
            ProductImage.objects.create(
                product=product, image=self.get_image(*image), sort_order=sort_order
            )
        for sort_order, variant in enumerate(data["variants"]):
            variant = dict(variant)
            if "price" in variant:
                variant["price"] = Decimal(variant["price"])
            if "image" in variant:
                variant["image"] = self.get_image(*variant["image"])
            ProductVariant.objects.create(product=product, sort_order=sort_order, **variant)
        self.created.append(f"product '{product.name}'")

    def get_image(self, title, colour, size=(800, 800)):
        collection = self.get_collection()
        image = Image.objects.filter(collection=collection, title=title).first()
        if image is not None:
            return image
        img = PILImage.new("RGB", size, colour)
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, size[0] - 40, size[1] - 40], outline="white", width=10)
        draw.text(
            (size[0] // 2, size[1] // 2),
            title,
            fill="white",
            anchor="mm",
            font=ImageFont.load_default(size=size[1] // 12),
        )
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        filename = f"seed-{title.lower().replace(' ', '-')}.png"
        return Image.objects.create(
            title=title, collection=collection, file=ImageFile(buffer, name=filename)
        )

    def get_collection(self):
        collection = Collection.objects.filter(name=IMAGE_COLLECTION).first()
        if collection is None:
            collection = Collection.get_first_root_node().add_child(name=IMAGE_COLLECTION)
        return collection

    def create_sale(self):
        start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=30)
        if Sale.objects.filter(start_date__lt=end, end_date__gt=start).exists():
            self.skipped.append("sale (a sale already exists for these dates)")
            return
        product = Product.objects.filter(
            category__slug=SALE_CATEGORY, name=SALE_PRODUCT
        ).first()
        if product is None:
            self.skipped.append(f"sale ('{SALE_PRODUCT}' not found)")
            return
        sale = Sale.objects.create(
            name="Seed sale",
            start_date=start,
            end_date=end,
            banner_include_end=True,
        )
        SaleProduct.objects.create(sale=sale, product=product, discount=20)
        self.created.append(f"sale '{sale.name}' (20% off '{product.name}')")
