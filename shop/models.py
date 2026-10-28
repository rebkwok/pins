from datetime import timedelta
from itertools import groupby
from typing import NamedTuple
from decimal import ROUND_HALF_UP, Decimal

import logging
import secrets
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.template.defaultfilters import pluralize
from django.dispatch import Signal
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.html import format_html, format_html_join
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
from wagtail.admin.panels import (
    FieldPanel,
    FieldRowPanel,
    HelpPanel,
    InlinePanel,
    MultiFieldPanel,
    Panel,
)
from wagtail.admin.panels.base import get_form_for_model
from wagtail.contrib.forms.models import validate_to_address
from wagtail.contrib.settings.models import (
    BaseGenericSetting,
    register_setting,
)
from wagtail.fields import RichTextField
from wagtail.images.models import Image
from wagtail.models import Collection, Page, Orderable

from common.users import real_users_q


# DISPATCHERS

# The group of users who send (or hold, for collection) some of the shop's
# products. They see their items to send in the admin, and are emailed about new
# orders with their items for products that are set to email them (otherwise,
# the shop's notify recipients, who get all new orders, tell them).
DISPATCHERS_GROUP = "Dispatchers"


def dispatcher_choices():
    """The users who can be chosen as dispatchers (not the view-as preview users)"""
    return Q(groups__name=DISPATCHERS_GROUP) & real_users_q()


def is_dispatcher(user):
    return user is not None and user.groups.filter(name=DISPATCHERS_GROUP).exists()


def dispatcher_name(user):
    return user.get_full_name() or user.get_username()



# ORDERS


SHIPPING_COLLECT = "collect"
SHIPPING_DELIVER = "deliver"
# For baskets and orders with no items that need shipping
SHIPPING_NONE = "none"
# The methods customers can choose, in the order they're shown in the basket;
# delivery is the default
SHIPPING_METHODS = {SHIPPING_DELIVER: "Delivery", SHIPPING_COLLECT: "Collect in person"}
SHIPPING_METHOD_CHOICES = {**SHIPPING_METHODS, SHIPPING_NONE: "No shipping needed"}
# The basket's labels for the shipping methods, where they differ
SHIPPING_METHOD_BASKET_LABELS = {SHIPPING_COLLECT: "Collect in person (prior arrangement only)"}
# Warnings shown with the shipping method options in the basket
SHIPPING_METHOD_NOTES = {
    SHIPPING_COLLECT: (
        "Not available for most items. Only choose this if you have contacted "
        "PINS and confirmed that you can collect all items in your order in "
        "person."
    ),
}

logger = logging.getLogger(__name__)


UK = "United Kingdom"
# Checkout details saved on the basket (see views.save_checkout_details), which
# become the order's
CHECKOUT_DETAILS = ("phone", "safe_place", "country", "consent_at")


class Order(OrderAmountsMixin, BaseOrder):
    name = models.CharField(max_length=255, verbose_name="Name")
    shipping_method = models.CharField(
        choices=tuple(SHIPPING_METHOD_CHOICES.items()), default=SHIPPING_DELIVER
    )
    phone = models.CharField(max_length=40, blank=True, verbose_name="Mobile number")
    # For delivery
    safe_place = models.CharField(max_length=255, blank=True, verbose_name="Safe place")
    country = models.CharField(
        max_length=100, blank=True, help_text="The delivery address's country."
    )
    consent_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Data processing consent given"
    )

    @property
    def needs_delivery(self):
        return self.shipping_method == SHIPPING_DELIVER

    @property
    def outside_uk(self):
        """
        Delivered outside the UK (shipping outside the UK isn't standard: the
        customer should have arranged it first)
        """
        return self.needs_delivery and bool(self.country) and self.country != UK

    @transaction.atomic
    def populate_from_basket(
        self,
        basket,
        request,
        **kwargs,
    ) -> None:
        basket.extra["basket_id"] = basket.id
        self.name = basket.extra.pop("name", "")
        for field in CHECKOUT_DETAILS:
            value = basket.extra.pop(field, None)
            if value:
                setattr(self, field, value)
        self.shipping_method = basket.shipping_method
        if self.status == self.Status.PROCESSING and not basket.requires_shipping:
            # A paid order with nothing to ship is complete. It's created
            # complete (not changed to complete), so the customer gets one email.
            self.status = self._current_status = self.Status.COMPLETED
        super().populate_from_basket(basket, request, **kwargs)
        # The discount code applied to the basket (if any) has now been used
        code = self.discount_code
        if code:
            DiscountCode.objects.filter(code=code).update(
                order=self, basket=None, date_used=timezone.now()
            )

    @property
    def discount_row(self):
        """The order's extra row for its discount code (label, amount etc), or None"""
        for row in self.extra_rows:
            if row.get("modifier") == DISCOUNT_ROW:
                return row
        return None

    @property
    def discount_code(self):
        """The discount code applied to the order, or None"""
        row = self.discount_row
        return row["extra"].get("code") if row else None

    # Shipping (or collection)

    @property
    def is_collected(self):
        return self.shipping_method == SHIPPING_COLLECT

    def _set_items_status(self, items, status, user):
        """
        Set the shipping status of the order's items (those still to send), and
        update the order's status. Returns the items changed.
        """
        # Lock the order, so concurrent updates (e.g. two dispatchers) see each
        # other's items
        Order.objects.select_for_update().filter(pk=self.pk).first()
        to_change = list(
            self.items.filter(
                pk__in=[item.pk for item in items],
                shipping_status=OrderItem.TO_SEND,
            )
        )
        now = timezone.now()
        for item in to_change:
            item.shipping_status = status
            item.shipped_at = now
            item.shipped_by = user
            item.save(update_fields=["shipping_status", "shipped_at", "shipped_by"])
        if to_change:
            self.update_shipping_status()
        return to_change

    @transaction.atomic
    def mark_items_shipped(self, items, user):
        """
        Mark the order's items (those still to send) as shipped (or collected) by
        user, update the order's status, and email the customer.
        Returns the items marked shipped.
        """
        from . import activity

        shipped = self._set_items_status(items, OrderItem.SHIPPED, user)
        if shipped:
            activity.log_items(self, activity.ORDER_SHIPPED, shipped, user=user)
            items_shipped.send(sender=Order, order=self, items=shipped)
        return shipped

    @transaction.atomic
    def mark_items_not_sent(self, items, user):
        """
        Mark the order's items (those still to send) as won't be sent (e.g. out of
        stock), and update the order's status. The customer isn't emailed (they
        need to be told, and refunded, separately).
        Returns the items changed.
        """
        from . import activity

        changed = self._set_items_status(items, OrderItem.NOT_SENT, user)
        if changed:
            activity.log_items(self, activity.ORDER_NOT_SENT, changed, user=user)
        return changed

    def update_shipping_status(self):
        """
        Partially shipped once some (but not all) of the items that need shipping
        have been shipped; Shipped once they all have (ignoring items that won't
        be sent). Only orders being processed (or partly shipped) are changed.
        """
        if self.status not in (self.Status.PROCESSING, self.Status.PARTIALLY_SHIPPED):
            return
        statuses = set(
            self.items.exclude(
                shipping_status__in=[OrderItem.NO_SHIPPING, OrderItem.NOT_SENT]
            ).values_list("shipping_status", flat=True)
        )
        if OrderItem.SHIPPED not in statuses:
            return
        new_status = (
            self.Status.PARTIALLY_SHIPPED
            if OrderItem.TO_SEND in statuses
            else self.Status.SHIPPED
        )
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status", "date_updated"])

    @property
    def items_to_send(self):
        return self.items.filter(shipping_status=OrderItem.TO_SEND)

    @property
    def can_ship_items(self):
        """Whether items can be marked shipped (the order has been paid)"""
        return self.status in (
            self.Status.PROCESSING,
            self.Status.PARTIALLY_SHIPPED,
            self.Status.SHIPPED,
            self.Status.COMPLETED,
        )

    def can_change_status(self, status):
        return status in self.Status.get_transitions().get(self.status, [])

    @property
    def can_complete(self):
        """
        Whether the order can be marked completed: once everything that needs
        shipping (or collecting) has been
        """
        return (
            self.can_change_status(self.Status.COMPLETED)
            and not self.items_to_send.exists()
        )

    @property
    def display_status(self):
        """The order's status in plain words, for shop admins"""
        Status = self.Status
        shipped = "Collected" if self.is_collected else "Shipped"
        if self.status in (Status.NEW, Status.CREATED, Status.HOLD):
            label = "Awaiting payment"
        elif self.status == Status.FAILED:
            label = "Payment failed"
        elif self.status == Status.PROCESSING:
            if not self.is_paid:
                label = "Processing"
            elif not self.items_to_send.exists():
                # e.g. none of its items will be sent
                label = "Paid – nothing to send"
            else:
                label = f"Paid – ready to {'collect' if self.is_collected else 'ship'}"
        elif self.status == Status.PARTIALLY_SHIPPED:
            label = f"Partly {shipped.lower()}"
        elif self.status == Status.SHIPPED:
            label = shipped
        else:
            # Completed, cancelled, refunded
            label = self.status_display
        if self.refund_status == "Partially refunded":
            label += " (partly refunded)"
        return label


class OrderItem(BaseOrderItem):
    """
    An order item, with its dispatcher (copied from its product when the order
    is placed, so reassigning the product later doesn't change past orders) and
    shipping status.
    """

    TO_SEND = "to_send"
    SHIPPED = "shipped"
    NO_SHIPPING = "no_shipping"
    # e.g. out of stock (refunded separately)
    NOT_SENT = "not_sent"
    SHIPPING_STATUSES = {
        TO_SEND: "Ready to send",
        # Collected items (for "collect in person" orders) are marked shipped too
        SHIPPED: "Shipped/collected",
        NO_SHIPPING: "No shipping needed",
        NOT_SENT: "Won't be sent",
    }

    dispatcher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dispatched_order_items",
    )
    # A copy of the dispatcher's name, kept if the user is deleted
    dispatcher_name = models.CharField(max_length=255, blank=True)
    shipping_status = models.CharField(
        max_length=20, choices=tuple(SHIPPING_STATUSES.items()), default=TO_SEND
    )
    # When, and by whom, the item was marked shipped/collected (or won't be sent)
    shipped_at = models.DateTimeField(null=True, blank=True)
    shipped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def populate_from_basket_item(self, item, request):
        super().populate_from_basket_item(item, request)
        product = item.product.product
        self.dispatcher = product.dispatcher
        if product.dispatcher is not None:
            self.dispatcher_name = dispatcher_name(product.dispatcher)
        self.shipping_status = (
            self.TO_SEND if product.requires_shipping else self.NO_SHIPPING
        )

    @property
    def needs_shipping(self):
        return self.shipping_status != self.NO_SHIPPING


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

    # Key in extra for the discount code applied to the basket
    DISCOUNT_CODE_KEY = "discount_code"

    @property
    def discount_code(self):
        """The DiscountCode applied to the basket, or None"""
        code = self.extra.get(self.DISCOUNT_CODE_KEY)
        return DiscountCode.find(code) if code else None

    def set_discount_code(self, code):
        """Apply a DiscountCode to the basket (or remove it, with None)"""
        if code is None:
            self.extra.pop(self.DISCOUNT_CODE_KEY, None)
        else:
            self.extra[self.DISCOUNT_CODE_KEY] = code.code
        self.save()

    def claim_discount_code(self):
        """
        Claim the basket's discount code (if any) for its payment, so it can't be
        used for another order meanwhile. Returns an error message if it can't be
        used any more, otherwise None. Call in a transaction.
        """
        code_value = self.extra.get(self.DISCOUNT_CODE_KEY)
        if not code_value:
            return None
        code = DiscountCode.objects.select_for_update().filter(code=code_value).first()
        reason = DISCOUNT_CODE_INVALID if code is None else code.unavailable_reason(self)
        if reason:
            return reason
        code.basket = self
        code.save(update_fields=["basket"])
        return None

    def clear(self):
        super().clear()
        self._remove_discount_code()

    def remove(self, ref):
        super().remove(ref)
        if not self.items.exists():
            self._remove_discount_code()

    def _remove_discount_code(self):
        """
        The basket is empty (its last item was removed, or it timed out): remove
        its discount code, so it isn't still applied when the customer next
        shops
        """
        if self.extra.pop(self.DISCOUNT_CODE_KEY, None) is not None:
            self.save(update_fields=["extra"])

    def release_discount_code(self):
        """The basket's payment has ended without an order: release its code"""
        DiscountCode.objects.filter(basket=self, order__isnull=True).update(basket=None)

    def end_payment(self):
        super().end_payment()
        self.release_discount_code()

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

    # update() (and so reset_timeout) is called several times whenever the
    # basket is displayed (salesman's serializer updates the basket for each
    # item), so the timeout isn't saved again if it was reset this recently
    TIMEOUT_RESET_INTERVAL = timedelta(seconds=10)

    def reset_timeout(self):
        timeout = timezone.now() + timedelta(minutes=settings.BASKET_TIMEOUT_MINUTES)
        if self.payment_in_progress and self.timeout and self.timeout > timeout:
            # Don't release items before the checkout session expires
            return
        if (
            self.timeout
            and timedelta(0) <= timeout - self.timeout < self.TIMEOUT_RESET_INTERVAL
        ):
            # Reset just now
            return
        logger.debug("Resetting basket timeout")
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
            basket.release_discount_code()
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


class CategoryProductsPanel(Panel):
    """
    On a category's page: its products, dragged into their order on the shop
    (saved straight away, see admin_views.CategoryProductsReorderView)
    """

    class BoundPanel(Panel.BoundPanel):
        template_name = "shop/admin/panels/category_products.html"

        def get_context_data(self, parent_context=None):
            from wagtail.admin.ui.tables import BooleanColumn, Column, Table, TitleColumn
            from wagtail.admin.ui.tables.orderable import OrderableTableMixin, OrderingColumn

            class OrderingHeaderColumn(OrderingColumn):
                # (not the listings' "Sort" toggle: the products are always in order)
                header_template_name = "shop/admin/panels/ordering_header.html"

            class CategoryProductsTable(OrderableTableMixin, Table):
                @property
                def ordering_column(self):
                    return OrderingHeaderColumn("ordering", width="80px", sort_key="sort_order")

            context = super().get_context_data(parent_context)
            context["request"] = self.request
            category = self.instance
            if not category.pk:
                return context
            products = list(category.products.order_by("sort_order", "name"))
            can_reorder = self.request.user.has_perm("shop.change_product")
            context["products"] = products
            context["can_reorder"] = can_reorder and len(products) > 1
            context["table"] = CategoryProductsTable(
                [
                    TitleColumn(
                        "name",
                        label="Product",
                        get_url=lambda product: reverse(
                            "wagtailsnippets_shop_product:edit", args=(product.pk,)
                        ),
                    ),
                    Column("variants", label="Variants", accessor="get_variant_count"),
                    BooleanColumn("live", label="Live"),
                ],
                products,
                sort_order_field="sort_order",
                reorder_url=(
                    reverse("shop_category_products_reorder", args=(category.pk, 999999))
                    if context["can_reorder"]
                    else None
                ),
            )
            return context


class Category(models.Model):
    """
    A category of products: products are grouped by category on the shop page,
    which can show one category at a time (/shop/?category=<slug>)
    """

    title = models.CharField(max_length=255, help_text="Shown on the shop page.")
    slug = models.SlugField(
        max_length=255,
        unique=True,
        blank=True,
        verbose_name="Web address",
        help_text=(
            "The shop's web address with this category selected, e.g. 'clothing' "
            "for /shop/?category=clothing. Made from the title if left blank."
        ),
    )
    description = RichTextField(
        blank=True, help_text="Optional text shown on the shop page when this category is selected."
    )
    # The order on the shop page (categories are reordered in the Categories list)
    sort_order = models.IntegerField(null=True, blank=True, editable=False)

    panels = [
        FieldPanel("title"),
        FieldPanel("slug"),
        FieldPanel("description"),
        CategoryProductsPanel(heading="Products"),
    ]

    class Meta:
        ordering = ["sort_order", "title"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(Lower("title"), name="unique_category_title")
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if not self.title:
            return
        others = Category.objects.exclude(pk=self.pk)
        # Unique titles, so customers and the shop stock lists can tell the
        # categories apart
        if others.filter(title__iexact=self.title).exists():
            raise ValidationError(
                {"title": f"There's already a category called '{self.title}'."}
            )
        slug_from_title = not self.slug
        self.slug = self.slug or slugify(self.title)
        # (the slug field may not be on the form, e.g. when creating a category
        # from a product's category chooser)
        field = "title" if slug_from_title else "slug"
        if others.filter(slug=self.slug).exists():
            raise ValidationError(
                {field: f"Another category already has the web address '{self.slug}'."}
            )

    def save(self, *args, **kwargs):
        self.slug = self.slug or slugify(self.title)
        if self.sort_order is None:
            # New categories go last
            last = Category.objects.aggregate(last=models.Max("sort_order"))["last"]
            self.sort_order = 0 if last is None else last + 1
        super().save(*args, **kwargs)

    def get_product_count(self):
        return f"{self.live_products.count()} live ({self.products.count()} total)"

    get_product_count.short_description = "Products"

    def products_link(self):
        """The category's product count, linking to its products in the admin"""
        return format_html(
            '<a href="{}?category={}">{}</a>',
            reverse("wagtailsnippets_shop_product:list"),
            self.pk,
            self.get_product_count(),
        )

    products_link.short_description = "Products"

    @property
    def live_products(self):
        # products are live if they are set to live AND have at least one live variants
        return (
            self.products.filter(live=True, variants__isnull=False, variants__live=True)
            .order_by("sort_order", "name")
            .distinct()
        )

    def get_url(self, request=None):
        """The shop page with this category selected (None if there's no live shop page)"""
        shop_page = ShopPage.objects.live().first()
        if shop_page is None:
            return None
        return f"{shop_page.get_url(request)}?category={self.slug}"

    def shop_link(self):
        """The shop page with this category selected, for the admin list"""
        url = self.get_url()
        return format_html('<a href="{}">View on the shop</a>', url) if url else "-"

    shop_link.short_description = "On the shop"


class ShippingRate(models.Model):
    """
    A delivery cost that products are given (e.g. "Small items", £3.50). A
    delivered basket's shipping is the highest rate of its items that need
    shipping, charged once. One rate is the default, which new products start
    with.
    """

    name = models.CharField(
        max_length=100, unique=True, help_text="e.g. Small items, Standard."
    )
    amount = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Cost",
    )
    default = models.BooleanField(
        default=False,
        help_text=(
            "New products start with this rate. Ticking it here unticks the "
            "current default."
        ),
    )

    panels = [FieldPanel("name"), FieldPanel("amount"), FieldPanel("default")]

    class Meta:
        ordering = ["amount", "name"]

    def __str__(self):
        return f"{self.name} (£{self.amount:,.2f})"

    def clean(self):
        super().clean()
        was_default = (
            self.pk is not None
            and ShippingRate.objects.filter(pk=self.pk, default=True).exists()
        )
        if was_default and not self.default:
            raise ValidationError(
                {
                    "default": (
                        "There must be a default rate: tick \"Default\" on another "
                        "rate instead."
                    )
                }
            )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            others = ShippingRate.objects.exclude(pk=self.pk)
            if self.default:
                others.filter(default=True).update(default=False)
            elif not others.filter(default=True).exists():
                # The first rate is the default
                self.default = True
            super().save(*args, **kwargs)

    @classmethod
    def get_default(cls):
        return cls.objects.filter(default=True).first()

    def cost(self):
        return f"£{self.amount:,.2f}"

    cost.short_description = "Cost"
    cost.admin_order_field = "amount"

    def products_count(self):
        return self.products.count()

    products_count.short_description = "Products"


class ShopFAQ(models.Model):
    """A question and answer on the shop's FAQs page (/shop/faqs/)"""

    question = models.CharField(max_length=255)
    answer = RichTextField()
    # The order on the FAQs page (reordered in the FAQs list)
    sort_order = models.IntegerField(null=True, blank=True, editable=False)

    panels = [FieldPanel("question"), FieldPanel("answer")]

    class Meta:
        ordering = ["sort_order", "pk"]
        verbose_name = "shop FAQ"
        verbose_name_plural = "shop FAQs"

    def __str__(self):
        return self.question

    def save(self, *args, **kwargs):
        if self.sort_order is None:
            # New FAQs go last
            last = ShopFAQ.objects.aggregate(last=models.Max("sort_order"))["last"]
            self.sort_order = 0 if last is None else last + 1
        super().save(*args, **kwargs)


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


SHARED_STOCK_COLOUR_SIZE_MESSAGE = (
    "Variants that share stock can't have a colour or size: sharing stock is for "
    "the same item sold singly or in packs. Remove the colour and size, or untick "
    "'Variants share stock' on the product."
)

PACK_SIZE_NOT_SHARED_MESSAGE = (
    "Items per pack is only used when the product's variants share stock: tick "
    "'Variants share stock' on the product, or set this to 1."
)


def is_blank_variant(data):
    """data: a variant's (cleaned) field values"""
    return not (data.get("variant_name") or data.get("colour") or data.get("size"))


class RelativeStockFormMixin:
    """
    For admin forms of models with a stock field (variants, and products whose
    variants share stock), which also declare a stock_shown field.

    Stock is changed relative to the stock shown when the form was loaded, so
    that stock taken or returned by customers' baskets while the form is being
    edited isn't overwritten. E.g. if the form showed 10 and is saved with 15,
    but 2 have been added to baskets meanwhile (so stock is 8), stock becomes 13.
    """

    def _init_stock_shown(self):
        if self.instance.pk is not None:
            self.fields["stock_shown"].initial = self.instance.stock

    def _clean_stock(self, cleaned_data):
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
            type(self.instance)
            .objects.filter(pk=self.instance.pk)
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

    def _apply_stock_change(self):
        stock_shown = self.cleaned_data.get("stock_shown")
        if self.instance.pk is not None and stock_shown is not None:
            change = self.cleaned_data["stock"] - stock_shown
            # Saving with an F expression adds the change to the stock in the
            # database (UPDATE ... SET stock = stock + change). Django then reads
            # the new value back into the instance.
            self.instance.stock = models.F("stock") + change


def add_colour_size_errors(form, cleaned_data):
    """Variants that share stock can't have a colour or size"""
    for field in ("colour", "size"):
        if cleaned_data.get(field):
            form.add_error(field, SHARED_STOCK_COLOUR_SIZE_MESSAGE)


class ProductVariantAdminForm(RelativeStockFormMixin, WagtailAdminModelForm):
    """
    Admin form for product variants, on their own and in the product form.
    Stock is changed relative to the stock shown (see RelativeStockFormMixin).

    If the product's variants share stock (or it has no stock limit), the
    variant's own stock isn't used, so it isn't in the form (or shown). (Its pack size is always shown, so it can be
    set in the same save as ticking the product's "Variants share stock".)
    """

    # The stock when the form was loaded (a submitted field, so it's kept if the
    # form is redisplayed with errors)
    stock_shown = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_stock_shown()
        product = self.instance.product if self.instance.product_id is not None else None
        if product is not None and (product.shares_stock or product.unlimited_stock):
            del self.fields["stock"]
            del self.fields["stock_shown"]

    def clean(self):
        cleaned_data = super().clean()
        self._check_variant_names(cleaned_data)
        # On the variant's own page (in the product form, ProductAdminForm checks
        # this, as "Variants share stock" may be ticked in the same save)
        product = cleaned_data.get("product")
        if product is not None:
            if not product.shares_stock and (cleaned_data.get("pack_size") or 1) > 1:
                self.add_error("pack_size", PACK_SIZE_NOT_SHARED_MESSAGE)
            if product.shares_stock:
                add_colour_size_errors(self, cleaned_data)
        return self._clean_stock(cleaned_data)

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

    def is_made_live(self):
        """Whether saving makes an existing (not live) variant live"""
        return (
            self.instance.pk is not None
            and "live" in self.changed_data
            and self.cleaned_data.get("live")
        )

    def save(self, commit=True):
        made_live = self.is_made_live()
        self._apply_stock_change()
        variant = super().save(commit=commit)
        # A variant made live again may have stock left from before, which may
        # not be right any more (see the after_edit_snippet hook)
        variant.stock_reminders = stock_reminders([variant] if made_live else [])
        return variant


def stock_reminders(variants):
    """
    Reminders to check the stock of variants that have just been made live (see
    ProductVariant.stock_reminder), using their saved stock (the forms save stock
    as a change, so the instances may not have it)
    """
    reminders = []
    for variant in variants:
        variant.refresh_from_db(fields=["stock"])
        variant.product.refresh_from_db(fields=["stock"])
        reminder = variant.stock_reminder()
        if reminder:
            reminders.append(reminder)
    return reminders


class StockFieldPanel(FieldPanel):
    """
    Panel for a stock field (of a variant, or a product whose variants share
    stock), which includes the form's hidden stock_shown field (rendered with
    the stock field, rather than as its own empty panel)
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


def _list_icon(name, classname, text, colour=None):
    """
    A Wagtail admin icon for a list column, with text for screen readers (and as
    a tooltip)
    """
    style = "width: 1em; height: 1em; vertical-align: -0.125em;"
    if colour:
        style += f" color: {colour};"
    return format_html(
        '<span title="{}"><svg class="icon icon-{} {}" aria-hidden="true" style="{}">'
        '<use href="#icon-{}"></use></svg><span class="w-sr-only">{}</span></span>',
        text,
        name,
        classname,
        style,
        name,
        text,
    )


class MessagePanel(HelpPanel):
    """
    A message box (e.g. a warning) worked out for the instance being edited,
    by the BoundPanel's get_message(), and only shown if there's a message.
    (The box's style is on the message itself: a HelpPanel's classname is also
    put on its section, which would make a box within a box.)
    """

    message_class = "help-info"

    class BoundPanel(HelpPanel.BoundPanel):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            message = self.get_message()
            self.content = (
                format_html(
                    '<div class="help-block {}">{}</div>', self.panel.message_class, message
                )
                if message
                else ""
            )

        def get_message(self):
            return None

        def is_shown(self):
            return bool(self.content)


class DispatcherWarningPanel(MessagePanel):
    """
    On a product's page: a warning if its dispatcher isn't in the Dispatchers
    group any more (shown only then)
    """

    message_class = "help-warning"

    class BoundPanel(MessagePanel.BoundPanel):
        def get_message(self):
            return self.instance.dispatcher_warning


class VariantStockHelpPanel(MessagePanel):
    """
    On a variant's own edit page: whether the product's variants share stock
    (which is set on the product's page), with a link to the product's page
    """

    class BoundPanel(MessagePanel.BoundPanel):
        def get_message(self):
            product = self.instance.product if self.instance.product_id else None
            if product is None:
                return (
                    "Variants of the same product can share stock (e.g. single cards "
                    "and packs of 5): this is set on the product's page."
                )
            url = reverse("wagtailsnippets_shop_product:edit", args=(product.pk,))
            if product.unlimited_stock:
                return format_html(
                    "This product has no stock limit, so its variants' stock isn't "
                    'counted. This is set on the <a href="{}">product\'s page</a>.',
                    url,
                )
            if product.shares_stock:
                return format_html(
                    "This product's variants share stock: <strong>{}</strong> single "
                    "items in stock, from which this variant uses its items per "
                    "pack. Change the shared stock on the "
                    '<a href="{}">product\'s page</a>.',
                    product.stock,
                    url,
                )
            # Only a suggestion if the variants could share stock: more than one,
            # without colours or sizes (which would be different items)
            variants = product.variants.all()
            if len(variants) < 2 or any(v.colour or v.size for v in variants):
                return None
            return format_html(
                "To sell this product's variants from the same stock (e.g. single "
                "cards and packs of 5), tick 'Variants share stock' on the "
                '<a href="{}">product\'s page</a>.',
                url,
            )


# (in rows, so each variant takes less room on the product's page; the rows'
# inputs line up, see wagtail_hooks.shop_admin_css)
PRODUCT_VARIANT_PANELS = [
    FieldRowPanel(
        [FieldPanel("variant_name"), FieldPanel("colour"), FieldPanel("size")],
        classname="shop-field-row",
    ),
    FieldRowPanel(
        [FieldPanel("price"), StockFieldPanel("stock"), FieldPanel("pack_size")],
        classname="shop-field-row",
    ),
    FieldRowPanel([FieldPanel("image"), FieldPanel("live")], classname="shop-field-row"),
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


UNLIMITED_SHARED_MESSAGE = (
    "A product with no stock limit can't share stock between its variants: untick "
    "one of them."
)


class ProductAdminForm(RelativeStockFormMixin, WagtailAdminModelForm):
    """
    The product's shared stock (used if its variants share stock) is changed
    relative to the stock shown (see RelativeStockFormMixin).
    """

    stock_shown = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_stock_shown()
        shipping_rate_field = self.fields.get("shipping_rate")
        if shipping_rate_field is not None and self.instance.pk is None:
            # New products start with the default rate
            default_rate = ShippingRate.get_default()
            if default_rate is not None:
                self.initial.setdefault("shipping_rate", default_rate.pk)
        dispatcher_field = self.fields.get("dispatcher")
        if dispatcher_field is not None:
            # Users' names, not usernames
            dispatcher_field.label_from_instance = dispatcher_name
        if dispatcher_field is not None and self.instance.dispatcher_id is not None:
            # Keep the product's dispatcher as a choice even if they've been
            # removed from the Dispatchers group (there's a warning), so saving
            # the product doesn't remove them unless another is chosen
            dispatcher_field.queryset = (
                dispatcher_field.queryset
                | dispatcher_field.queryset.model.objects.filter(
                    pk=self.instance.dispatcher_id
                )
            ).distinct()

    def save(self, commit=True):
        # Variants made live (see ProductVariantAdminForm.save), checked before
        # saving
        variants_formset = self.formsets.get("variants")
        made_live = [
            form.instance
            for form in (variants_formset.forms if variants_formset else [])
            if not variants_formset._should_delete_form(form) and form.is_made_live()
        ]
        self._apply_stock_change()
        product = super().save(commit=commit)
        product.stock_reminders = stock_reminders(made_live)
        return product

    def _check_pack_sizes(self, cleaned_data):
        """
        Variants can only have more than 1 item per pack if the product's
        variants share stock (which may be ticked in the same save), and
        variants that share stock can't have a colour or size
        """
        variants_formset = self.formsets.get("variants")
        if variants_formset is None:
            return
        variants_formset.errors  # clean the variant forms
        for form in variants_formset.forms:
            if variants_formset._should_delete_form(form):
                continue
            variant_data = getattr(form, "cleaned_data", None) or {}
            if cleaned_data.get("shares_stock"):
                add_colour_size_errors(form, variant_data)
            elif (variant_data.get("pack_size") or 1) > 1:
                form.add_error("pack_size", PACK_SIZE_NOT_SHARED_MESSAGE)

    def clean(self):
        cleaned_data = super().clean()
        self._clean_stock(cleaned_data)
        if cleaned_data.get("unlimited_stock") and cleaned_data.get("shares_stock"):
            self.add_error("unlimited_stock", UNLIMITED_SHARED_MESSAGE)
        self._check_pack_sizes(cleaned_data)
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

    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )

    name = models.CharField(max_length=255)

    description = RichTextField(help_text="Shown with the product in the shop.", blank=True)
    price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=10,
        help_text="The price of each variant, unless the variant has its own.",
    )
    # The order in its category on the shop (products are dragged into order on
    # the category's page in the admin)
    sort_order = models.IntegerField(null=True, blank=True, editable=False)
    live = models.BooleanField(
        default=True,
        help_text="Shown in the shop (with its live variants). Untick to hide it.",
    )
    unlimited_stock = models.BooleanField(
        default=False,
        verbose_name="No stock limit",
        help_text=(
            "Tick for things that can't run out, e.g. competition entries or items "
            "made to order: stock isn't counted, and they're never out of stock."
        ),
    )
    shares_stock = models.BooleanField(
        default=False,
        verbose_name="Variants share stock",
        help_text=(
            "Tick if the variants are sold from the same stock, e.g. single items "
            "and packs of 5. Then set the shared stock below."
        ),
    )
    stock = models.IntegerField(
        default=0,
        verbose_name="Shared stock",
        help_text=(
            "The number of single items in stock, if the variants share stock (not "
            "counting items in customers' baskets)."
        ),
    )
    dispatcher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dispatched_products",
        limit_choices_to=dispatcher_choices,
        help_text=(
            "Who sends (or holds, for collection) this product: a user in the "
            "Dispatchers group. Changing it moves the product's items still to "
            "send in existing orders to the new dispatcher."
        ),
    )
    notify_dispatcher = models.BooleanField(
        default=False,
        verbose_name="Email the dispatcher about new orders",
        help_text=(
            "Email the dispatcher when an order with this product is paid. If not, "
            "the shop's notify email recipients (who get all new orders) need to "
            "tell them."
        ),
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
    shipping_rate = models.ForeignKey(
        ShippingRate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products",
        help_text=(
            "The delivery cost for this product (rates are set in Shop admin > "
            "Shipping rates). If a basket has products with different rates, the "
            "highest is charged, once."
        ),
    )

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("category"),
                FieldPanel("name"),
                FieldPanel("description"),
                FieldPanel("price"),
                FieldPanel("live"),
            ],
            heading="Product",
        ),
        InlinePanel(
            "product_images",
            heading="Images",
            label="Image",
            help_text=(
                "Shown in this order (use the arrows to reorder them), followed by "
                "the images of the product's live variants."
            ),
        ),
        MultiFieldPanel(
            [
                FieldPanel("unlimited_stock"),
                FieldPanel("shares_stock"),
                StockFieldPanel("stock"),
            ],
            heading="Stock",
        ),
        ProductVariantsInlinePanel(
            "variants",
            panels=PRODUCT_VARIANT_PANELS,
            heading="Variants",
            label="Variant",
            help_text=mark_safe(
                """What customers choose from when they buy this product. Every
            product needs at least one.
            <ul>
            <li>One option (e.g. a mug): one variant, with no name, colour or
              size.</li>
            <li>Sizes or colours (e.g. T-shirts): a variant for each, e.g. colour
              Black, size S.</li>
            <li>Versions (e.g. Men's and Women's hoodies): a name for each.</li>
            <li>Packs (e.g. Single and Pack of 5): tick "Variants share stock"
              above, then give each variant its items per pack.</li>
            </ul>"""
            ),
        ),
        MultiFieldPanel(
            [
                FieldPanel("requires_shipping"),
                FieldPanel("shipping_rate", widget=forms.Select),
                DispatcherWarningPanel(),
                FieldPanel("dispatcher"),
                FieldPanel("notify_dispatcher"),
            ],
            heading="Shipping",
        ),
    ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.requires_shipping and self.shipping_rate_id is None:
            # e.g. imported products: the default rate
            self.shipping_rate = ShippingRate.get_default()
        if self.pk and self.sort_order is not None:
            # moved to another category: last in the new one
            old_category = (
                Product.objects.filter(pk=self.pk).values_list("category_id", flat=True).first()
            )
            if old_category != self.category_id:
                self.sort_order = None
        if self.sort_order is None:
            # New products go last in their category
            last = (
                Product.objects.filter(category_id=self.category_id)
                .exclude(pk=self.pk)
                .aggregate(last=models.Max("sort_order"))["last"]
            )
            self.sort_order = 0 if last is None else last + 1
        old_dispatcher = (
            Product.objects.filter(pk=self.pk).values_list("dispatcher_id", flat=True).first()
            if self.pk
            else None
        )
        super().save(*args, **kwargs)
        if self.pk and old_dispatcher != self.dispatcher_id:
            self.reassign_items_to_send()

    def reassign_items_to_send(self):
        """
        The product's dispatcher has changed: its items still to send (or hand
        over) in orders go to the new dispatcher. (Items already sent, or that
        won't be sent, keep the dispatcher who had them.) Sets admin_messages,
        for the admin to show.
        """
        items = order_items_for_variants(list(self.variants.values_list("id", flat=True))).filter(
            shipping_status=OrderItem.TO_SEND
        )
        order_count = items.values("order_id").distinct().count()
        count = items.update(
            dispatcher=self.dispatcher,
            dispatcher_name=dispatcher_name(self.dispatcher) if self.dispatcher else "",
        )
        if count:
            to = (
                f"now have {dispatcher_name(self.dispatcher)} as their dispatcher"
                if self.dispatcher
                else "now have no dispatcher"
            )
            self.admin_messages = [
                f"{count} item{pluralize(count)} still to send, in {order_count} "
                f"order{pluralize(order_count)}, {to}."
            ]

    def clean(self):
        if self.requires_shipping and self.shipping_rate_id is None:
            raise ValidationError(
                {"shipping_rate": "Choose a shipping rate for a product that needs shipping."}
            )
        if self.notify_dispatcher:
            if self.dispatcher_id is None:
                raise ValidationError(
                    {"notify_dispatcher": "Choose a dispatcher to email."}
                )
            if not self.dispatcher.email:
                raise ValidationError(
                    {
                        "notify_dispatcher": (
                            f"{dispatcher_name(self.dispatcher)} has no email address."
                        )
                    }
                )

    @property
    def delivery_cost(self):
        """
        The product's shipping rate's amount (the default rate's if it has none),
        or None if it doesn't need shipping (or there are no rates)
        """
        if not self.requires_shipping:
            return None
        rate = self.shipping_rate or ShippingRate.get_default()
        return rate.amount if rate is not None else None

    @property
    def dispatcher_warning(self):
        """
        A warning if the product's dispatcher isn't in the Dispatchers group any
        more (so can't be chosen again, and can't see their items to send)
        """
        if self.dispatcher is not None and not is_dispatcher(self.dispatcher):
            return (
                f"{dispatcher_name(self.dispatcher)} isn't in the Dispatchers group "
                "any more. Choose another dispatcher."
            )
        return None

    def shipping_display(self):
        """The product's delivery cost, for the admin list"""
        cost = self.delivery_cost
        if cost is None:
            return "Not shipped" if not self.requires_shipping else "-"
        return f"£{cost:,.2f}"

    shipping_display.short_description = "Shipping"

    def dispatcher_display(self):
        """
        The product's dispatcher, for the admin list, with an icon if they're
        emailed about new orders, and a warning if they're not a dispatcher any
        more
        """
        if self.dispatcher is None:
            return ""
        icons = []
        if self.notify_dispatcher:
            icons.append(
                _list_icon("mail", "shop-dispatcher-emailed", "Emailed about new orders")
            )
        warning = self.dispatcher_warning
        if warning:
            icons.append(
                _list_icon("warning", "shop-dispatcher-warning", warning, colour="#cd3238")
            )
        return format_html(
            "{}{}",
            dispatcher_name(self.dispatcher),
            format_html_join("", " {}", ((icon,) for icon in icons)),
        )

    dispatcher_display.short_description = "Dispatcher"

    def get_variant_count(self):
        return f"{self.live_variants.count()} live ({self.variants.count()} total)"

    get_variant_count.short_description = "# variants"

    def variants_link(self):
        """The product's variant count, linking to its variants in the admin"""
        return format_html(
            '<a href="{}?product={}">{}</a>',
            reverse("wagtailsnippets_shop_productvariant:list"),
            self.pk,
            self.get_variant_count(),
        )

    variants_link.short_description = "Variants"

    @property
    def live_variants(self):
        return self.variants.filter(live=True)

    @cached_property
    def price_summary(self):
        """
        The product's price for the shop: its live variants' lowest price (with
        any sale discount), whether variants' prices differ ("From £12.00"), and
        the price before the sale discount, if the lowest price is discounted.
        None if there are no live variants.
        """
        prices = [
            (variant.get_discounted_price() or variant.base_price, variant.base_price)
            for variant in self.live_variants
        ]
        if not prices:
            return None
        price, was = min(prices)
        return PriceSummary(
            price=price,
            was=was if was != price else None,
            varies=len({current for current, _ in prices}) > 1,
        )

    def out_of_stock(self):
        """
        Nothing from this product can be added to the basket: no live variant has
        any stock (or, if the variants share stock, there isn't enough for any of
        their pack sizes). (Variants that aren't live don't count, even if they
        have stock.)
        """
        if self.unlimited_stock:
            return not self.live_variants.exists()
        if self.shares_stock:
            return not self.live_variants.filter(pack_size__lte=self.stock).exists()
        return not self.live_variants.filter(stock__gt=0).exists()

    @property
    def identifier(self):
        return slugify(f"{self.category.title}-{self.name}")

    def category_link(self):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("wagtailsnippets_shop_category:edit", args=(self.category_id,)),
            self.category.title,
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


# The image collection that the shop's images are filed in (created by migration
# 0017); shop admins can only see the images in it
SHOP_COLLECTION = "Shop"


def get_shop_collection():
    """The Shop collection (under the root collection), created if necessary"""
    root = Collection.get_first_root_node()
    collection = root.get_children().filter(name=SHOP_COLLECTION).first()
    return collection or root.add_child(name=SHOP_COLLECTION)


def file_in_shop_collection(image):
    """
    File an image used by the shop in the Shop collection, if it's in the root
    collection (images filed in other collections are left where they are)
    """
    if image is not None and image.collection.is_root():
        image.collection = get_shop_collection()
        image.save(update_fields=["collection"])


class PriceSummary(NamedTuple):
    """A product's price, for the shop (see Product.price_summary)"""

    price: Decimal
    # the price before a sale discount
    was: Decimal | None
    # whether the variants' prices differ ("From £...")
    varies: bool


# Stock at or below this is shown as "Only 3 left" in the shop
LOW_STOCK = 5


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
            "Blank if there's only one variant, or the variants only differ by "
            "colour or size."
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
        help_text="Blank for the product's price.",
    )
    stock = models.IntegerField(
        default=1,
        help_text=(
            "In stock, not counting customers' baskets. Your change is added to the "
            "current stock when you save, so baskets' changes meanwhile aren't lost."
        ),
    )
    pack_size = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Items per pack",
        help_text="With shared stock: e.g. 5 for a pack of 5.",
    )
    live = models.BooleanField(
        default=True, help_text="Shown in the shop."
    )

    colour = models.CharField(blank=True, default="")
    size = models.CharField(blank=True, default="")

    # Inherit Orderable's Meta, so variants are ordered by sort_order
    class Meta(Orderable.Meta):
        constraints = [
            # stock calculations divide by the pack size
            models.CheckConstraint(
                condition=Q(pack_size__gte=1), name="pack_size_at_least_1"
            ),
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

    # Stock. A variant's stock is its own, unless the product's variants share
    # stock: then it's the product's stock, in single items, and the variant uses
    # pack_size items from it. Basket quantities are in variants (e.g. packs).

    @property
    def stock_holder(self):
        """The variant, or the product if its variants share stock"""
        return self.product if self.product.shares_stock else self

    @property
    def items_per_unit(self):
        """How many items of stock one of this variant uses"""
        return self.pack_size if self.product.shares_stock else 1

    @property
    def available(self):
        """
        How many of this variant can be added to baskets; None if there's no
        limit (the product has no stock limit)
        """
        if self.product.unlimited_stock:
            return None
        return self.stock_holder.stock // self.items_per_unit

    def has_stock_for(self, quantity, in_basket=0):
        """
        Whether there's stock for this quantity of the variant, if the basket
        already has in_basket of it (which have been taken from stock)
        """
        if self.product.unlimited_stock:
            return True
        return self.stock_holder.stock + (in_basket - quantity) * self.items_per_unit >= 0

    def stock_display(self):
        """
        The variant's stock, for the admin list. A variant that isn't live is
        marked, as its stock may be out of date.
        """
        not_live = "" if self.live else ", not live"
        if self.product.unlimited_stock:
            return f"No limit{' (not live)' if not self.live else ''}"
        if not self.product.shares_stock:
            return f"{self.stock} (not live)" if not self.live else self.stock
        if self.pack_size == 1:
            return f"{self.product.stock} (shared stock{not_live})"
        return f"{self.available} packs (from {self.product.stock} shared{not_live})"

    def stock_reminder(self):
        """
        A reminder to check the stock, when the variant is made live (its stock
        may not be right any more); None if it has no stock to sell (or no stock
        limit)
        """
        if self.product.unlimited_stock:
            return None
        if self.product.shares_stock:
            if self.available <= 0:
                return None
            return (
                f"{self} is now live, sold from the product's shared stock of "
                f"{self.product.stock}. Check that's still right."
            )
        if self.stock <= 0:
            return None
        return f"{self} is now live with {self.stock} in stock. Check that's still right."

    stock_display.short_description = "Stock"

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

    @property
    def current_price(self):
        """The variant's price now, with any sale discount"""
        return self.get_discounted_price() or self.base_price

    def stock_note(self):
        """
        For the shop: "Out of stock", or "Only 3 left" if stock is low (nothing
        if there's no stock limit)
        """
        available = self.available
        if available is None:
            return ""
        if available <= 0:
            return "Out of stock"
        if available <= LOW_STOCK:
            return f"Only {available} left"
        return ""

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
    category_link.admin_order_field = "product__category__title"

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
                category_id=self.product.category_id
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
    subpage_types = ["home.FormPage", "home.StandardPage"]

    def categories(self):
        return Category.objects.all()

    def children(self):
        return self.categories()

    def get_context(self, request, *args, **kwargs):
        """
        The shop's products, grouped by category in the shop's order: searched
        (?q=) and one category (?category=<slug>) from the address
        """
        context = super().get_context(request, *args, **kwargs)
        query = request.GET.get("q", "").strip()
        category_slug = request.GET.get("category", "")

        products = (
            Product.objects.filter(live=True, variants__live=True)
            .distinct()
            .select_related("category")
            .order_by("category__sort_order", "category__title", "sort_order", "name")
        )
        total = products.count()
        if query:
            products = products.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(category__title__icontains=query)
            )
        if category_slug:
            products = products.filter(category__slug=category_slug)
        products = list(products)

        context.update(
            query=query,
            category=Category.objects.filter(slug=category_slug).first() if category_slug else None,
            category_slug=category_slug,
            total=total,
            # (the categories with live products, for the category buttons)
            filter_categories=[
                category for category in self.categories() if category.live_products.exists()
            ],
            products=products,
            product_groups=[
                (category, list(category_products))
                for category, category_products in groupby(
                    products, key=lambda product: product.category
                )
            ],
        )
        return context


NO_NOTIFY_ADDRESSES_WARNING = (
    "Nobody is emailed about new shop orders: add an email address to "
    "'Email new orders to'."
)


class NotifyAddressesWarningPanel(MessagePanel):
    """On the shop settings: a warning if nobody is emailed about new orders"""

    message_class = "help-warning"

    class BoundPanel(MessagePanel.BoundPanel):
        def get_message(self):
            return None if self.instance.notify_email_addresses else NO_NOTIFY_ADDRESSES_WARNING


@register_setting(icon="cogs")
class ShopSettings(BaseGenericSetting):
    notify_email_addresses = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Email new orders to",
        help_text=(
            "Every new order is emailed to these addresses (separate them with "
            "commas). Dispatchers are only emailed about products set to email "
            "them, so whoever gets these emails passes the rest on."
        ),
        validators=[validate_to_address],
    )
    reply_to = models.EmailField(
        max_length=255,
        blank=True,
        verbose_name="Reply-to address",
        help_text=(
            "Optional: where replies to the shop's emails (to customers and "
            "dispatchers) go."
        ),
    )

    panels = [
        NotifyAddressesWarningPanel(),
        FieldPanel("notify_email_addresses"),
        FieldPanel("reply_to"),
    ]

    class Meta:
        verbose_name = "Shop settings"


class SaleCategory(models.Model):
    """
    A sale discount for a category
    """

    sale = ParentalKey("Sale", related_name="sale_categories")
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    discount = models.PositiveIntegerField(
        default=10, validators=[MaxValueValidator(100)]
    )

    class Meta:
        unique_together = ("sale", "category")

    def __str__(self):
        # e.g. "Mugs (20% off)" (in the activity log)
        return f"{self.category} ({self.discount}% off)" if self.category_id else f"{self.discount}% off"


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

    def __str__(self):
        # e.g. "Mugs (20% off)" (in the activity log)
        return f"{self.product} ({self.discount}% off)" if self.product_id else f"{self.discount}% off"


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


# SHIPPING

# Some of an order's items have been shipped (or collected).
# Arguments: order, items (the items just shipped)
items_shipped = Signal()


# DISCOUNT CODES

# The basket's (and order's) extra row for a discount code
DISCOUNT_ROW = "discount-code"

# Stripe's minimum card payment in GBP; a discount can't leave less than this to
# pay (but can cover the whole basket, which then doesn't need a card payment)
MIN_CARD_PAYMENT = Decimal("0.30")

# Letters and numbers that can't be confused with each other (no 0/O or 1/I/L)
DISCOUNT_CODE_CHARACTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DISCOUNT_CODE_LENGTH = 8

DISCOUNT_CODE_INVALID = "Invalid discount code."
DISCOUNT_CODE_USED = "Discount code already used."
# (A code being paid for in another basket; it may become valid again if that
# payment is cancelled)
DISCOUNT_CODE_IN_USE = "Discount code is no longer valid."
# (It would leave less than a card payment's minimum to pay; rare, and a
# customer who's used a code to pay nothing wouldn't expect it, so not explained)
DISCOUNT_CODE_TOO_LITTLE_LEFT = "Discount cannot be applied to this basket."


class DiscountCode(models.Model):
    """
    A single-use code for a fixed amount off the whole basket (including
    shipping, and after sale prices).

    A code is claimed by a basket when its payment starts (so it can't be used
    for two orders at once), released if the payment is cancelled or expires,
    and used when the order is created.
    """

    FIXED_AMOUNT = "fixed"

    code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text=(
            "What customers enter, e.g. PINS5OFF (not case-sensitive). Leave blank "
            "to create a random code."
        ),
    )
    # Only fixed amounts for now (percentages could be added later)
    discount_type = models.CharField(
        max_length=20,
        choices=[(FIXED_AMOUNT, "Fixed amount")],
        default=FIXED_AMOUNT,
        editable=False,
    )
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text=(
            "Taken off the whole basket, including shipping. If it's more than the "
            "basket's total, the order is free, and the rest isn't refunded."
        ),
    )
    active = models.BooleanField(
        default=True, help_text="Untick to stop the code being used."
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional, for your reference (e.g. who it was given to). Not shown to customers.",
    )
    date_created = models.DateTimeField(auto_now_add=True)
    # The basket whose payment has claimed the code
    basket = models.ForeignKey(
        "shop.Basket",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )
    order = models.ForeignKey(
        "shop.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="discount_codes",
        editable=False,
    )
    date_used = models.DateTimeField(null=True, blank=True, editable=False)

    panels = [
        FieldPanel("code"),
        FieldPanel("amount"),
        FieldPanel("active"),
        FieldPanel("description"),
    ]

    class Meta:
        ordering = ("-date_created",)

    def __str__(self):
        return self.code

    @staticmethod
    def normalise(code):
        return (code or "").strip().upper()

    @classmethod
    def generate_code(cls):
        while True:
            code = "".join(
                secrets.choice(DISCOUNT_CODE_CHARACTERS)
                for _ in range(DISCOUNT_CODE_LENGTH)
            )
            if not cls.objects.filter(code=code).exists():
                return code

    def clean(self):
        self.code = self.normalise(self.code) or self.generate_code()

    def save(self, *args, **kwargs):
        self.code = self.normalise(self.code) or self.generate_code()
        super().save(*args, **kwargs)

    @classmethod
    def find(cls, code):
        """The code (not case-sensitive), or None"""
        return cls.objects.filter(code=cls.normalise(code)).first()

    def unavailable_reason(self, basket):
        """
        Why the code can't be used for the basket, or None if it can. A code
        claimed by the basket's payment can still be used for it, even if it has
        been disabled since.
        """
        if self.order_id is not None:
            return DISCOUNT_CODE_USED
        if self.basket_id is not None and self.basket_id == basket.id:
            return None
        if not self.active:
            return DISCOUNT_CODE_INVALID
        if self.basket_id is not None and self.basket_is_paying():
            return DISCOUNT_CODE_IN_USE
        return None

    def basket_is_paying(self):
        return self.basket is not None and self.basket.payment_in_progress

    def status(self):
        if self.order_id is not None:
            return f"Used (order {self.order})"
        if self.basket_is_paying():
            return "Payment in progress"
        if not self.active:
            return "Disabled"
        return "Available"

    status.short_description = "Status"
