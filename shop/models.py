from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import logging
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils.text import slugify
from django.utils.safestring import mark_safe
from django.utils import timezone
from salesman.basket.models import BASKET_ID_SESSION_KEY, BaseBasket, BaseBasketItem
from salesman.orders.models import (
    BaseOrder,
    BaseOrderItem,
    BaseOrderNote,
    BaseOrderPayment,
)
from modelcluster.models import ClusterableModel, ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel, HelpPanel, MultiFieldPanel
from wagtail.contrib.forms.models import validate_to_address
from wagtail.contrib.settings.models import (
    BaseGenericSetting,
    register_setting,
)
from wagtail.fields import RichTextField
from wagtail.models import Page, Orderable


# ORDERS


SHIPPING_METHODS = {"collect": "Collect in store", "deliver": "Delivery"}

logger = logging.getLogger(__name__)


class Order(BaseOrder):
    name = models.CharField(max_length=255, verbose_name="Name")
    shipping_method = models.CharField(
        choices=tuple(SHIPPING_METHODS.items()), default="collect"
    )

    @transaction.atomic
    def populate_from_basket(
        self,
        basket,
        request,
        **kwargs,
    ) -> None:
        basket.extra["basket_id"] = basket.id
        self.name = basket.extra.pop("name", "")
        self.shipping_method = basket.shipping_method
        return super().populate_from_basket(basket, request, **kwargs)


class OrderItem(BaseOrderItem):
    pass


class OrderPayment(BaseOrderPayment):
    pass


class OrderNote(BaseOrderNote):
    pass


# BASKET


class Basket(BaseBasket):
    shipping_method = models.CharField(
        choices=tuple(SHIPPING_METHODS.items()), default="collect"
    )
    timeout = models.DateTimeField(null=True)

    # Key in extra for the Stripe checkout session while a payment is in progress
    STRIPE_SESSION_KEY = "stripe_session"

    @classmethod
    def get_existing(cls, request):
        """
        Return the basket for this request, or None if there isn't one yet.
        Unlike salesman's Basket.objects.get_or_create_from_request, this doesn't
        create a basket (or a session) for visitors who haven't added anything to
        their basket.
        """
        user = getattr(request, "user", None)
        session = getattr(request, "session", None)
        basket_id = session.get(BASKET_ID_SESSION_KEY) if session is not None else None
        if user is not None and user.is_authenticated:
            if basket_id is not None:
                # The user has a basket from before they logged in; let salesman
                # merge it into their user basket
                basket, _ = cls.objects.get_or_create_from_request(request)
                return basket
            return cls.objects.filter(user=user).first()
        if basket_id is not None:
            return cls.objects.filter(id=basket_id, user=None).first()
        return None

    @property
    def payment_in_progress(self):
        """
        A Stripe checkout session has been started for this basket and hasn't
        completed or expired; the basket can't be changed until it does.
        """
        return self.STRIPE_SESSION_KEY in self.extra

    @property
    def stripe_session_id(self):
        return self.extra.get(self.STRIPE_SESSION_KEY, {}).get("id")

    @property
    def stripe_session_url(self):
        return self.extra.get(self.STRIPE_SESSION_KEY, {}).get("url")

    def start_payment(self, session_id, session_url, hold_until):
        """
        Record the Stripe checkout session for this basket, and hold the
        basket's items until hold_until
        """
        self.extra[self.STRIPE_SESSION_KEY] = {"id": session_id, "url": session_url}
        self.timeout = hold_until
        self.save()

    def end_payment(self):
        """The basket's Stripe checkout session has expired or been cancelled"""
        self.extra.pop(self.STRIPE_SESSION_KEY, None)
        self.save()

    def update(self, request):
        super().update(request)
        self.reset_timeout()

    def merge(self, other):
        super().merge(other)
        # salesman's merge adds the other basket's items without calling
        # update(), so start the timeout here; otherwise the merged items would
        # never expire
        if self.items.exists():
            self.reset_timeout()

    def reset_timeout(self):
        timeout = timezone.now() + timedelta(minutes=settings.BASKET_TIMEOUT_MINUTES)
        if self.payment_in_progress and self.timeout and self.timeout > timeout:
            # Don't release items before the checkout session expires
            # (update() is called whenever the basket is displayed)
            return
        logger.info("Resetting basket timeout")
        self.timeout = timeout
        self.save()

    @classmethod
    def clear_expired(cls):
        """
        Remove the items from baskets whose timeout has passed, returning them
        to stock. Only baskets that still have items are cleared, and their
        timeout is reset so that they aren't processed again.
        Returns the number of baskets cleared.
        """
        expired = cls.objects.filter(
            timeout__lt=timezone.now(), items__isnull=False
        ).distinct()
        count = 0
        for basket in expired:
            basket.clear()
            basket.timeout = None
            # Any checkout session has expired by now
            basket.extra.pop(cls.STRIPE_SESSION_KEY, None)
            basket.save(update_fields=["timeout", "extra"])
            count += 1
        if count:
            logger.info("Cleared %s expired basket(s)", count)
        return count

    @classmethod
    def delete_stale(cls, days):
        """
        Delete empty baskets that haven't been updated for the given number of days.
        Baskets that an order has been created from (with basket_id in extra) are
        skipped, as deleting them adjusts stock for the order (see signals).
        Returns the number of baskets deleted.
        """
        cutoff = timezone.now() - timedelta(days=days)
        stale = cls.objects.filter(
            items__isnull=True, date_updated__lt=cutoff
        ).exclude(extra__has_key="basket_id")
        _, deleted = stale.delete()
        count = deleted.get(cls._meta.label, 0)
        if count:
            logger.info("Deleted %s stale empty basket(s)", count)
        return count


class BasketItem(BaseBasketItem):
    @property
    def name(self):
        # Note product here is a ProductVariant instance
        return self.product.name if self.product else "(no name)"


# PRODUCTS


class CategoryPage(Page):
    body = RichTextField(
        verbose_name="Page body",
        blank=True,
        help_text="Optional text to describe the category",
    )
    index = models.PositiveIntegerField(
        default=100, help_text="Used for ordering categories on the shop page"
    )

    content_panels = Page.content_panels + [
        FieldPanel("body"),
        FieldPanel("index"),
    ]

    parent_page_types = ["ShopPage"]
    subpage_types = ["CategoryPage", "home.StandardPage"]

    def get_product_count(self):
        return f"{self.live_products.count()} live ({self.page_products.count()} total)"

    get_product_count.short_description = "# products"

    @property
    def live_products(self):
        # products are live if they are set to live AND have at least one live variants
        return (
            self.page_products.filter(
                live=True, variants__isnull=False, variants__live=True
            )
            .order_by("index")
            .distinct()
        )

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"


class Product(ClusterableModel):
    """
    Product, used to subgroup products in display.
    ProductVariant is the actual product that gets added to basket.
    """

    category_page = ParentalKey(CategoryPage, related_name="page_products")

    name = models.CharField(max_length=255)

    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Images can be added to product and/or product variants, all will be displayed",
    )
    description = RichTextField(help_text="Description of the product", blank=True)
    price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=10,
        help_text="Default price for this product. Can be overridden by setting price on individual variants.",
    )
    index = models.PositiveIntegerField(
        default=100, help_text="Used for ordering products on the category page"
    )
    live = models.BooleanField(
        default=True, help_text="Display this product in the shop"
    )

    panels = [
        HelpPanel(
            """
            A Product is an item for sale; it has a name and a description.
            
            Product variants represent the actual items that are sold, and may have attributes e.g. size
            and colour. Each product must have at least one variant in order to be available for sale.
            """
        ),
        FieldPanel("category_page"),
        FieldPanel("name"),
        FieldPanel("image"),
        FieldPanel("price"),
        FieldPanel("description"),
        FieldPanel("index"),
        FieldPanel("live"),
        InlinePanel(
            "variants",
            heading="Product variants",
            label="Variant",
            help_text=mark_safe(
                """A variant represents a single item that can be ordered/purchased. E.g.
            A product 'Pen' might have variants 'Single', 'Pack of 5', 'Pack of 10'.<br/>
            Can be left blank if there is only one variant for this product, or if it
            only varies by colour and/or size.<br/> 
            e.g.
            <ul>
            <li>Product Mug: one product variant, with no name, colour or size specifications.</li>
            <li>Product T-shirt: size/colour variants with no separate name (e.g. black,S)</li>
            <li>Product Hoodie: variants with name "Men's Hoodie", "Women's Hoodie", each 
              with size and colour options</li>
            </ul>
            Use the arrows to reorder items.
            """
            ),
        ),
    ]

    def __str__(self):
        return self.name

    def get_variant_count(self):
        return f"{self.live_variants.count()} live ({self.variants.count()} total)"

    get_variant_count.short_description = "# variants"

    @property
    def live_variants(self):
        return self.variants.filter(live=True)

    def out_of_stock(self):
        if self.variants.exists():
            return self.variants.aggregate(models.Sum("stock"))["stock__sum"] <= 0
        return True

    @property
    def identifier(self):
        return slugify(f"{self.category_page.title}-{self.name}")

    def category_link(self):
        return mark_safe(
            f"<a href={reverse('wagtailadmin_pages:edit', args=(self.category_page.id,))}>{self.category_page.title}</a>"
        )

    category_link.short_description = "Category"

    @property
    def images(self):
        all_images = list()
        if self.image:
            all_images.append(self.image)
        for variant in self.live_variants.filter(image__isnull=False):
            if variant.image not in all_images:
                all_images.append(variant.image)
        return all_images

    def get_absolute_url(self):
        return reverse("shop:product_detail", kwargs={"pk": self.pk})


class ProductVariant(Orderable):
    product = ParentalKey(Product, on_delete=models.CASCADE, related_name="variants")
    variant_name = models.CharField(
        null=True,
        blank=True,
        max_length=255,
        verbose_name="Variant name",
        help_text="Can be left blank if there is only one variant for this product.",
    )
    image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    price = models.DecimalField(
        null=True,
        blank=True,
        max_digits=18,
        decimal_places=2,
        help_text="Leave blank to use default product price.",
    )
    stock = models.IntegerField(
        default=1, help_text="Quantity of this item currently in stock"
    )
    live = models.BooleanField(
        default=True, help_text="Display this product variant in the shop"
    )

    colour = models.CharField(null=True, blank=True)
    size = models.CharField(null=True, blank=True)

    class Meta:
        unique_together = ("variant_name", "colour", "size")

    def __str__(self):
        product_name = self.product.name
        if self.variant_full_name():
            return f"{product_name} - {self.variant_full_name()}"
        return product_name

    @property
    def name(self):
        return str(self)

    def variant_full_name(self):
        name = self.variant_name or ""
        if name and (self.colour or self.size):
            name += " - "
        if self.colour:
            name += self.colour
            if self.size:
                name += ", "
        if self.size:
            name += self.size
        return name

    variant_full_name.short_description = "Variant name"

    def get_price(self, request):
        return self.price

    def name_and_price(self):
        discounted_price = self.get_discounted_price()
        if discounted_price:
            price_str = f"£{discounted_price} (was £{self.price})" 
        else:
            price_str = f"£{self.price}"
        if self.variant_full_name():
            return f"{self.variant_full_name()} - {price_str}"
        return (f"{price_str}")

    def category_link(self):
        return mark_safe(
            f"<a href={reverse('wagtailadmin_pages:edit', args=(self.product.category_page.id,))}>{self.product.category_page.title}</a>"
        )

    category_link.short_description = "Category"
    category_link.admin_order_field = "product__category_page__title"
    category_link.short_description = "Category"

    def get_sale_item(self):
        """
        Is this product variant currently on sale?
        Return a sale item (SaleCategory or SaleProduct) or None
        """
        current_sale = Sale.current_sale()
        if current_sale:
            # Look for products on sale first; these can override their category discounts
            sale_products = current_sale.sale_products.filter(product__id=self.product.id)
            if sale_products.exists():
                # A product with a discount of 0 is intended to remove this product from the sale altogether,
                # even if its overall category is on dale
                if sale_products.first().discount == 0:
                    return None
                return sale_products.first()
            sale_categories = current_sale.sale_categories.filter(
                category__id=self.product.category_page.id
            )
            if sale_categories.exists():
                return sale_categories.first()

    def get_discount_amount(self, sale_item):
        """
        Per-unit discount for this variant from the given sale item, rounded to the
        nearest penny. Used for both the displayed sale price and the basket discount,
        so the basket always charges quantity x the displayed price.
        """
        return (self.price * Decimal(sale_item.discount) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def get_discounted_price(self):
        sale_item = self.get_sale_item()
        if sale_item:
            return self.price - self.get_discount_amount(sale_item)

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
    subpage_types = ["home.FormPage", "home.StandardPage", "CategoryPage"]

    def categories(self):
        return CategoryPage.objects.live().order_by("index")

    def children(self):
        return self.categories()


@register_setting
class ShopSettings(BaseGenericSetting):
    notify_email_addresses = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Optional - new orders will be emailed to these addresses. "
            "Separate multiple addresses by comma."
        ),
        validators=[validate_to_address],
    )
    reply_to = models.EmailField(
        max_length=255,
        blank=True,
        help_text=("Optional - reply to email address for shop notification emails."),
    )

    panels = [
        FieldPanel("notify_email_addresses"),
        FieldPanel("reply_to"),
    ]


class SaleCategory(models.Model):
    """
    A sale discount for a category
    """

    sale = ParentalKey("Sale", related_name="sale_categories")
    category = models.ForeignKey("CategoryPage", on_delete=models.CASCADE)
    discount = models.PositiveIntegerField(
        default=10, validators=[MaxValueValidator(100)]
    )

    class Meta:
        unique_together = ("sale", "category")


class SaleProduct(models.Model):
    """
    A sale discount for a product
    """

    sale = ParentalKey("Sale", related_name="sale_products")
    product = models.ForeignKey("Product", on_delete=models.CASCADE)
    discount = models.PositiveIntegerField(
        default=10, validators=[MaxValueValidator(100)]
    )

    class Meta:
        unique_together = ("sale", "product")


class Sale(ClusterableModel):
    name = models.CharField(max_length=255)
    banner_title = models.CharField(
        blank=True,
        null=True,
        default="Sale now on!",
        help_text="Optional title to be shown in a banner on all shop pages when sale is active",
    )
    banner_content = models.TextField(
        blank=True,
        null=True,
        default="Discounts available across the shop.",
        help_text="Optional content to be shown in a banner on all shop pages when sale is active",
    )
    banner_include_end = models.BooleanField(
        default=False,
        help_text="Include end date in banner (displayed as 'Sale ends on dd mmm yyyy at HH:MM')",
        verbose_name="Include end date in banner",
    )
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()

    panels = [
        HelpPanel(
            """
            Add Sales here. Only one sale can be live at any one time.
            """
        ),
        FieldPanel("name"),
        FieldPanel("start_date"),
        FieldPanel("end_date"),
        MultiFieldPanel(
            [
                FieldPanel("banner_title"),
                FieldPanel("banner_content"),
                FieldPanel("banner_include_end"),
            ],
            heading="Banner options",
        ),
        InlinePanel(
            "sale_categories",
            heading="Sale Categories",
            label="Category",
            help_text="Define discounts to apply to entire categories of products.",
        ),
        InlinePanel(
            "sale_products",
            heading="Sale Products",
            label="Product",
            help_text=(
                "Define discounts for specific products. Note that if a product's category is also on sale, any "
                "discount defined here will override it. To exclude certain products from a category sale, define them "
                "here with a discount of 0."
            ),
        ),
    ]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="start_before_end_constraint",
            )
        ]

    @classmethod
    def current_sale(cls):
        live_sales = cls.objects.filter(
            start_date__lte=timezone.now(), end_date__gt=timezone.now()
        )
        if live_sales.exists():
            # sale is only actually live if there are products or categories on sale in it
            sale = live_sales.first()
            if sale.sale_categories.exists() or sale.sale_products.exists():
                return sale

    def __str__(self):
        return f"{self.name} ({self.start_date.strftime('%d%b%y')} - {self.end_date.strftime('%d%b%y')})"

    def clean(self):
        if not self.id:
            within_these_dates = Sale.objects.exclude(
                end_date__lt=self.start_date
            ).exclude(start_date__gt=self.end_date)
            if within_these_dates.exists():
                existing = within_these_dates.first()
                raise (
                    ValidationError(
                        f"A sale already exists for some of these dates ({existing})"
                    )
                )
        return super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
