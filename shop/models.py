from django.db import models
from django.utils.text import slugify
from django.urls import reverse

from salesman.basket.models import BaseBasket, BaseBasketItem
from salesman.orders.models import (
    BaseOrder,
    BaseOrderItem,
    BaseOrderNote,
    BaseOrderPayment,
)

from wagtail.fields import RichTextField
from wagtail.models import Orderable, Page
from wagtail.snippets.models import register_snippet
from wagtail.admin.panels import FieldPanel, HelpPanel, InlinePanel


# ORDERS


class Order(BaseOrder):
    pass


class OrderItem(BaseOrderItem):
    pass


class OrderPayment(BaseOrderPayment):
    pass


class OrderNote(BaseOrderNote):
    pass


# BASKET


class Basket(BaseBasket):
    pass


class BasketItem(BaseBasketItem):
    pass


# PRODUCTS


@register_snippet
class ProductCategory(models.Model):
    """
    Product category, used to categorise products in display.
    ProductVariant is the actual product that gets added to basket.
    e.g.
    Category = Clothing
    ProductType = T-shirt
    ProductVariant = Mens Medium
    or
    e.g.
    Category = Merchandise
    ProductType = Pen
    ProductVariant = Pack of 10
    """

    name = models.CharField(max_length=255)
    body = RichTextField(
        verbose_name="Page body",
        blank=True,
        help_text="Optional text to describe the category",
    )
    index = models.PositiveIntegerField(
        default=100, help_text="Used for ordering categories on the shop page"
    )
    live = models.BooleanField(
        default=True, help_text="Display this category in the shop"
    )

    class Meta:
        verbose_name_plural = "product categories"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("shop:productcategory_detail", kwargs={"pk": self.pk})

    def get_product_count(self):
        return f"{self.live_products.count()} live ({self.products.count()} total)"

    get_product_count.short_description = "# products"

    @property
    def live_products(self):
        # products are live if they are set to live AND have at least one variant
        return (
            self.products.filter(live=True, variants__isnull=False)
            .order_by("index")
            .distinct()
        )


class Product(models.Model):
    """
    Product, used to subgroup products in display.
    ProductVariant is the actual product that gets added to basket.
    """

    category = models.ForeignKey(
        ProductCategory, on_delete=models.CASCADE, related_name="products"
    )
    name = models.CharField(max_length=255)

    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    description = RichTextField(help_text="Description of the product", blank=True)
    index = models.PositiveIntegerField(
        default=100, help_text="Used for ordering products on the category page"
    )
    live = models.BooleanField(
        default=True, help_text="Display this product in the shop"
    )

    def __str__(self):
        return self.name

    def get_variant_count(self):
        return f"{self.live_variants.count()} live ({self.variants.count()} total)"

    get_variant_count.short_description = "# variants"

    @property
    def live_variants(self):
        return self.variants.filter(live=True)

    @property
    def identifier(self):
        return slugify(f"{self.category.name}-{self.name}")


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    name = models.CharField(
        max_length=255,
        verbose_name="Variant name",
        help_text="""
            A variant represents a single item that can be ordered/purchased. E.g.
            if the product is 'T-shirt', a variant might be "Black, Small".  A product
            'Pen' might have variants 'Single', 'Pack of 5', 'Pack of 10'     
        """,
    )
    price = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    live = models.BooleanField(
        default=True, help_text="Display this product variant in the shop"
    )

    # COLORS = [
    #     ("black", "Black"),
    #     ("grey", "Grey"),
    #     ("white", "White"),
    # ]
    # GENDERS = [
    #     ("m", "Mens"),
    #     ("w", "Womens"),
    #     ("u", "Unisex"),
    # ]
    # SIZES = [
    #     ("xxs", "XX-Small"),
    #     ("xs", "X-Small"),
    #     ("s", "Small"),
    #     ("m", "Medium"),
    #     ("l", "Large"),
    #     ("xl", "X-Large"),
    #     ("xxl", "XX-Large"),
    # ]
    # PACK_SIZES = [
    #     (
    #         (1, 1),
    #         (5, 5),
    #         (10, 10)
    #     )
    # ]

    # # Variant data
    # # Only pack size (default 1) is required
    # colour = models.CharField(max_length=50, choices=COLORS, null=True, blank=True)
    # gender = models.CharField(max_length=50, choices=GENDERS, null=True, blank=True)
    # size = models.CharField(max_length=50, choices=SIZES, null=True, blank=True)
    # pack_size = models.CharField(max_length=50, choices=PACK_SIZES, default=PACK_SIZES[0][0])

    def __str__(self):
        return f"{self.product.name} - {self.name}"

    def get_price(self, request):
        return self.price

    @property
    def category(self):
        return self.product.category

    def get_category(self):
        return self.category

    get_category.admin_order_field = "product__category"
    get_category.short_description = "Category"

    @property
    def code(self):
        return str(self.id)


class ShopPage(Page):
    introduction = models.TextField(help_text="Text to describe the page", blank=True)
    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Landscape mode only; horizontal width between 1000px and 3000px.",
    )
    body = RichTextField(verbose_name="Page body", blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("introduction"),
        FieldPanel("body"),
        FieldPanel("image"),
    ]

    parent_page_types = ["home.HomePage"]

    def categories(self):
        return ProductCategory.objects.filter(live=True).order_by("index")
