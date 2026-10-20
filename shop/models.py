from datetime import timedelta
from typing import NamedTuple
from decimal import ROUND_HALF_UP, Decimal

import logging
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.urls import reverse
from django.utils.html import format_html
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
from modelcluster.forms import BaseChildFormSet
from salesman_stripe_connect.mixins import OrderAmountsMixin, StripeBasketMixin
from modelcluster.models import ClusterableModel, ParentalKey
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel, InlinePanel, HelpPanel, MultiFieldPanel
from wagtail.admin.panels.base import get_form_for_model
from wagtail.contrib.forms.models import validate_to_address
from wagtail.contrib.settings.models import (
    BaseGenericSetting,
    register_setting,
)
from wagtail.fields import RichTextField
from wagtail.images.models import Image
from wagtail.models import Page, Orderable


# ORDERS


SHIPPING_COLLECT = "collect"
SHIPPING_DELIVER = "deliver"
# For baskets and orders with no items that need shipping
SHIPPING_NONE = "none"
# The methods customers can choose, in the order they're shown in the basket;
# delivery is the default
SHIPPING_METHODS = {SHIPPING_DELIVER: "Delivery", SHIPPING_COLLECT: "Collect in person"}
SHIPPING_METHOD_CHOICES = {**SHIPPING_METHODS, SHIPPING_NONE: "No shipping needed"}
# Shown with the shipping method options in the basket
SHIPPING_METHOD_NOTES = {
    SHIPPING_COLLECT: (
        "Only choose this if you have contacted PINS and confirmed that you can "
        "collect your order in person."
    ),
}

logger = logging.getLogger(__name__)


class Order(OrderAmountsMixin, BaseOrder):
    name = models.CharField(max_length=255, verbose_name="Name")
    shipping_method = models.CharField(
        choices=tuple(SHIPPING_METHOD_CHOICES.items()), default=SHIPPING_DELIVER
    )

    @property
    def needs_delivery(self):
        return self.shipping_method == SHIPPING_DELIVER

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


class Basket(StripeBasketMixin, BaseBasket):
    shipping_method = models.CharField(
        choices=tuple(SHIPPING_METHOD_CHOICES.items()), default=SHIPPING_DELIVER
    )
    timeout = models.DateTimeField(null=True)

    @property
    def requires_shipping(self):
        """
        Whether any of the basket's items need shipping (a basket with only
        e.g. competition entries doesn't). An empty basket doesn't.
        """
        return any(
            item.product is not None and item.product.product.requires_shipping
            for item in self.get_items()
        )

    @property
    def needs_delivery(self):
        """
        Whether the basket is delivered (so needs an address and shipping cost):
        it has items that need shipping, and isn't being collected. (A basket
        that was checked out with no items needing shipping, then had some
        added, is delivered unless collection is chosen.)
        """
        return self.requires_shipping and self.shipping_method != SHIPPING_COLLECT

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

    def start_payment(self, session_id, session_url, hold_until=None):
        """
        Record the Stripe checkout session for this basket, and hold the
        basket's items until hold_until
        """
        if hold_until is not None:
            self.timeout = hold_until
        super().start_payment(session_id, session_url)

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
    subpage_types = ["home.StandardPage"]

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


def _items_for_variants(item_model, variant_ids):
    # Basket and order items refer to their variant with a generic foreign key
    return item_model.objects.filter(
        product_content_type=ContentType.objects.get_for_model(ProductVariant),
        product_id__in=list(variant_ids),
    )


def basket_items_for_variants(variant_ids):
    return _items_for_variants(BasketItem, variant_ids)


def order_items_for_variants(variant_ids):
    return _items_for_variants(OrderItem, variant_ids)


def _they(count, singular, plural):
    return singular if count == 1 else plural


def protected_variants_message(variants):
    """
    Error message if any of these variants can't be deleted, because they've been
    ordered or are in customers' baskets; otherwise None.

    Salesman prevents deleting products that are in baskets, and a signal prevents
    deleting ordered variants (both raising ProtectedError, which is a server
    error in the admin); the admin checks this first and shows this message.
    """
    variants = list(variants)
    variant_ids = [variant.id for variant in variants]
    ordered_ids = set(
        order_items_for_variants(variant_ids).values_list("product_id", flat=True)
    )
    in_basket_ids = set(
        basket_items_for_variants(variant_ids).values_list("product_id", flat=True)
    )
    ordered = [str(variant) for variant in variants if variant.id in ordered_ids]
    # Ordered variants are only listed once
    in_baskets = [
        str(variant)
        for variant in variants
        if variant.id in in_basket_ids and variant.id not in ordered_ids
    ]
    count = len(ordered) + len(in_baskets)
    if not count:
        return None
    sentences = []
    if ordered:
        sentences.append(
            f"{', '.join(ordered)} can't be deleted because "
            f"{_they(len(ordered), 'it has', 'they have')} been ordered."
        )
    if in_baskets:
        sentences.append(
            f"{', '.join(in_baskets)} can't be deleted because "
            f"{_they(len(in_baskets), 'it is', 'they are')} in customers' baskets."
        )
    sentences.append(
        f"Make {_they(count, 'it', 'them')} not live instead, so "
        f"{_they(count, 'it', 'they')} can't be added to any more baskets."
    )
    return " ".join(sentences)


VARIANT_NEEDS_NAME_MESSAGE = (
    "When a product has more than one variant, each variant needs a name, "
    "colour or size, so customers can tell them apart."
)


def is_blank_variant(data):
    """data: a variant's (cleaned) field values"""
    return not (data.get("variant_name") or data.get("colour") or data.get("size"))


class ProductVariantAdminForm(WagtailAdminModelForm):
    """
    Admin form for product variants, on their own and in the product form.

    Stock is changed relative to the stock shown when the form was loaded, so
    that stock taken or returned by customers' baskets while the form is being
    edited isn't overwritten. E.g. if the form showed 10 and is saved with 15,
    but 2 have been added to baskets meanwhile (so stock is 8), stock becomes 13.
    """

    # The stock when the form was loaded (a submitted field, so it's kept if the
    # form is redisplayed with errors)
    stock_shown = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None:
            self.fields["stock_shown"].initial = self.instance.stock

    def clean(self):
        cleaned_data = super().clean()
        self._check_variant_names(cleaned_data)
        stock = cleaned_data.get("stock")
        stock_shown = cleaned_data.get("stock_shown")
        if stock is None:
            return cleaned_data
        if self.instance.pk is None or stock_shown is None:
            if stock < 0:
                self.add_error("stock", "Stock can't be negative.")
            return cleaned_data

        change = stock - stock_shown
        if change == 0:
            # Stock isn't changed (even if it's already negative)
            return cleaned_data
        current_stock = (
            ProductVariant.objects.filter(pk=self.instance.pk)
            .values_list("stock", flat=True)
            .first()
        )
        if current_stock is not None and current_stock + change < 0:
            message = "Stock can't be negative."
            if current_stock != stock_shown:
                message += (
                    f" It has changed from {stock_shown} to {current_stock} since this "
                    "page was loaded, because of items added to or removed from "
                    f"customers' baskets, so the lowest you can enter is "
                    f"{stock_shown - current_stock}."
                )
            self.add_error("stock", message)
        return cleaned_data

    def _check_variant_names(self, cleaned_data):
        """
        If the product has other variants, this variant and the others each need
        a name, colour or size. Only for the variant form on its own (which has
        the product field); in the product form, ProductVariantFormSet checks
        all the variants together.
        """
        product = cleaned_data.get("product")
        if "product" not in self.fields or product is None:
            return
        others = ProductVariant.objects.filter(product=product).exclude(
            pk=self.instance.pk
        )
        if not others.exists():
            return
        if is_blank_variant(cleaned_data):
            self.add_error("variant_name", VARIANT_NEEDS_NAME_MESSAGE)
        elif others.filter(variant_name="", colour="", size="").exists():
            self.add_error(
                None,
                f"{VARIANT_NEEDS_NAME_MESSAGE} Another variant of this product has no "
                "name, colour or size; give it one first.",
            )

    def save(self, commit=True):
        stock_shown = self.cleaned_data.get("stock_shown")
        if self.instance.pk is not None and stock_shown is not None:
            change = self.cleaned_data["stock"] - stock_shown
            # Saving with an F expression adds the change to the stock in the
            # database (UPDATE ... SET stock = stock + change). Django then reads
            # the new value back into the instance.
            self.instance.stock = models.F("stock") + change
        return super().save(commit=commit)


class StockFieldPanel(FieldPanel):
    """
    Panel for a variant's stock, which includes ProductVariantAdminForm's hidden
    stock_shown field (rendered with the stock field, rather than as its own
    empty panel)
    """

    def get_form_options(self):
        options = super().get_form_options()
        options["fields"] = [*options.get("fields", []), "stock_shown"]
        return options

    class BoundPanel(FieldPanel.BoundPanel):
        def render_html(self, parent_context=None):
            return format_html(
                "{}{}", super().render_html(parent_context), self.form["stock_shown"]
            )


PRODUCT_VARIANT_PANELS = [
    FieldPanel("variant_name"),
    FieldPanel("image"),
    FieldPanel("price"),
    StockFieldPanel("stock"),
    FieldPanel("live"),
    FieldPanel("colour"),
    FieldPanel("size"),
]


VARIANT_UNIQUE_FIELDS = ("variant_name", "colour", "size")


class ProductVariantFormSet(BaseChildFormSet):
    """
    The product form's variants, with clearer errors than Django's defaults
    ("Please correct the duplicate data for product, variant_name, colour and
    size, which must be unique.") for duplicate variants
    """

    def get_unique_error_message(self, unique_check):
        if set(unique_check) - {self.fk.name} == set(VARIANT_UNIQUE_FIELDS):
            return (
                "Two or more variants have the same name, colour and size. Each "
                "variant needs a different name, colour or size."
            )
        return super().get_unique_error_message(unique_check)

    def get_form_error(self):
        # Shown on each duplicate variant
        return "This variant has the same name, colour and size as another variant."

    def clean(self):
        super().clean()
        # The variants the product will have: not deleted, and not empty new rows
        variant_forms = [
            form
            for form in self.forms
            if hasattr(form, "cleaned_data")
            and not self._should_delete_form(form)
            and (form.instance.pk is not None or form.has_changed())
        ]
        if len(variant_forms) < 2:
            return
        blank_forms = [form for form in variant_forms if is_blank_variant(form.cleaned_data)]
        for form in blank_forms:
            form.add_error("variant_name", "This variant needs a name, colour or size.")
        if blank_forms:
            raise ValidationError(VARIANT_NEEDS_NAME_MESSAGE)


class ProductVariantsInlinePanel(InlinePanel):
    """
    InlinePanel for a product's variants, using ProductVariantAdminForm for each
    variant (InlinePanel builds the child forms from WagtailAdminModelForm,
    ignoring the child model's base_form_class), and ProductVariantFormSet.
    """

    def get_form_options(self):
        options = super().get_form_options()
        child_form_options = self.child_edit_handler.get_form_options()
        options["formsets"][self.relation_name]["formset"] = ProductVariantFormSet
        options["formsets"][self.relation_name]["form"] = get_form_for_model(
            self.db_field.related_model,
            form_class=ProductVariantAdminForm,
            defer_required_on_fields=child_form_options.get(
                "defer_required_on_fields", []
            ),
        )
        return options


class ProductAdminForm(WagtailAdminModelForm):
    def clean(self):
        cleaned_data = super().clean()
        # Variants removed from the product in the form can't be deleted if
        # they've been ordered or are in customers' baskets
        variants_formset = self.formsets.get("variants")
        if variants_formset is not None and variants_formset.is_valid():
            deleted_variants = [
                form.instance
                for form in variants_formset.deleted_forms
                if form.instance.pk is not None
            ]
            message = protected_variants_message(deleted_variants)
            if message:
                self.add_error(None, message)
        return cleaned_data


class Product(ClusterableModel):
    """
    Product, used to subgroup products in display.
    ProductVariant is the actual product that gets added to basket.
    """

    base_form_class = ProductAdminForm

    category_page = ParentalKey(CategoryPage, related_name="page_products")

    name = models.CharField(max_length=255)

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
    requires_shipping = models.BooleanField(
        default=True,
        verbose_name="Needs shipping",
        help_text=(
            "Untick for products that aren't posted or collected (e.g. competition "
            "entries). A basket with only these products doesn't ask for a shipping "
            "method or address, and has no shipping cost."
        ),
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
        InlinePanel(
            "product_images",
            heading="Images",
            label="Image",
            help_text=(
                "Shown in this order, followed by the images of the product's live "
                "variants. Use the arrows to reorder them."
            ),
        ),
        FieldPanel("price"),
        FieldPanel("description"),
        FieldPanel("index"),
        FieldPanel("live"),
        FieldPanel("requires_shipping"),
        ProductVariantsInlinePanel(
            "variants",
            panels=PRODUCT_VARIANT_PANELS,
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
        """
        Nothing from this product can be added to the basket: no live variant has
        any stock. (Variants that aren't live don't count, even if they have stock.)
        """
        return not self.live_variants.filter(stock__gt=0).exists()

    @property
    def identifier(self):
        return slugify(f"{self.category_page.title}-{self.name}")

    def category_link(self):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("wagtailadmin_pages:edit", args=(self.category_page.id,)),
            self.category_page.title,
        )

    category_link.short_description = "Category"

    @property
    def images(self):
        """
        The product's images in order, then its live variants' images (with the
        variant's name as alt text), without duplicates. Returns CarouselImages.
        """
        images = [
            CarouselImage(product_image.image, product_image.alt_text)
            for product_image in self.product_images.select_related("image")
        ]
        variants = self.live_variants.filter(image__isnull=False).select_related("image")
        for variant in variants:
            if variant.image not in [image.image for image in images]:
                images.append(CarouselImage(variant.image, variant.variant_full_name()))
        return images

    def get_absolute_url(self):
        return reverse("shop:product_detail", kwargs={"pk": self.pk})


class CarouselImage(NamedTuple):
    """An image in a product's carousel"""

    image: Image
    alt_text: str = ""

    @property
    def alt(self):
        return self.alt_text or self.image.default_alt_text


class ProductImage(Orderable):
    product = ParentalKey(Product, on_delete=models.CASCADE, related_name="product_images")
    image = models.ForeignKey("wagtailimages.Image", on_delete=models.CASCADE, related_name="+")
    alt_text = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Optional description of the image for people using screen readers. "
            "If blank, the image's own description (or title) is used."
        ),
    )

    panels = [FieldPanel("image"), FieldPanel("alt_text")]

    def __str__(self):
        return self.alt_text or self.image.title


class ProductVariant(Orderable):
    base_form_class = ProductVariantAdminForm

    product = ParentalKey(Product, on_delete=models.CASCADE, related_name="variants")
    variant_name = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Variant name",
        help_text=(
            "Can be left blank if there is only one variant for this product, or if "
            "it only varies by colour and/or size."
        ),
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
        help_text=(
            "Leave blank to use the product's price (which then also applies if the "
            "product's price is changed)."
        ),
    )
    stock = models.IntegerField(
        default=1,
        help_text=(
            "Quantity of this item currently in stock, not including items in "
            "customers' baskets. Your change is added to the current stock when you "
            "save, so items added to or removed from baskets meanwhile aren't lost."
        ),
    )
    live = models.BooleanField(
        default=True, help_text="Display this product variant in the shop"
    )

    colour = models.CharField(blank=True, default="")
    size = models.CharField(blank=True, default="")

    # Inherit Orderable's Meta, so variants are ordered by sort_order
    class Meta(Orderable.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["product", "variant_name", "colour", "size"],
                name="unique_product_variant",
                violation_error_message=(
                    "This product already has a variant with this name, colour "
                    "and size."
                ),
            )
        ]

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

    @property
    def base_price(self):
        """
        The variant's price before any sale discount: its own price, or the
        product's price if the variant doesn't have one
        """
        return self.price if self.price is not None else self.product.price

    base_price.fget.short_description = "Price"

    def get_price(self, request):
        return self.base_price

    def name_and_price(self):
        discounted_price = self.get_discounted_price()
        if discounted_price:
            price_str = f"£{discounted_price} (was £{self.base_price})"
        else:
            price_str = f"£{self.base_price}"
        if self.variant_full_name():
            return f"{self.variant_full_name()} - {price_str}"
        return (f"{price_str}")

    def category_link(self):
        return self.product.category_link()

    category_link.short_description = "Category"
    category_link.admin_order_field = "product__category_page__title"

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
        return (self.base_price * Decimal(sale_item.discount) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def get_discounted_price(self):
        sale_item = self.get_sale_item()
        if sale_item:
            return self.base_price - self.get_discount_amount(sale_item)

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
        return CategoryPage.objects.child_of(self).live().order_by("index")

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
        if self.start_date and self.end_date:
            # A sale is current from its start date up to (but not including) its
            # end date, so one sale can start when another ends
            overlapping = Sale.objects.filter(
                start_date__lt=self.end_date, end_date__gt=self.start_date
            ).exclude(pk=self.pk)
            if overlapping.exists():
                raise ValidationError(
                    f"A sale already exists for some of these dates ({overlapping.first()})"
                )
        return super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
