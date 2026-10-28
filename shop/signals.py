# signals.py
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import F
from django.db.models import ProtectedError
from django.db.models.signals import post_delete, post_init, post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.html import format_html

from salesman.core.utils import get_salesman_model
from salesman.orders.signals import status_changed
from wagtail.models import ModelLogEntry
from salesman_stripe_connect import signals as stripe_signals

from . import activity
from .emails import Email, Items, Link, Paragraph
from .models import (
    OrderItem,
    OrderPayment,
    ProductImage,
    ProductVariant,
    ShopSettings,
    file_in_shop_collection,
    items_shipped,
    order_items_for_variants,
)


BasketItem = get_salesman_model("BasketItem")
Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")

logger = logging.getLogger(__name__)


def get_email_settings():
    shop_email_settings = ShopSettings.load()
    notify_emails = shop_email_settings.notify_email_addresses
    if notify_emails:
        notify_emails = [
            email.strip()
            for email in shop_email_settings.notify_email_addresses.split(",")
        ]
    reply_to = [shop_email_settings.reply_to or settings.DEFAULT_FROM_EMAIL]
    return notify_emails, reply_to


def customer_footer():
    """The footer for emails to customers (from Shop settings)"""
    return ShopSettings.load().email_footer


def _send_email_now(email, to, reply_to):
    """
    Send an Email (see emails.py), as HTML and plain text. Failures are logged
    rather than raised, so that a failed email can't fail the request that
    created or updated the order (e.g. the Stripe webhook).
    """
    message = EmailMultiAlternatives(
        email.subject, email.text, settings.DEFAULT_FROM_EMAIL, to, reply_to=reply_to
    )
    message.attach_alternative(email.html, "text/html")
    try:
        message.send()
    except Exception:
        logger.exception("Error sending email '%s' to %s", email.subject, to)


def send_email(email, to, reply_to):
    """Send an Email once the current transaction has committed"""
    transaction.on_commit(lambda: _send_email_now(email, to, reply_to))


def order_subject(order, about):
    """Shop emails' subjects, e.g. "PINS shop order 2026-00001 has been received" """
    return f"PINS shop order {order.ref}{about}"


def order_admin_url(order):
    """The order's page in the orders admin, for emails to the shop"""
    return f"https://{settings.DOMAIN}{reverse('shop_orders:edit', args=(order.pk,))}"


def order_status_url(order):
    return f'https://{settings.DOMAIN}{reverse("shop:order_status", args=(order.token,))}'


@receiver(stripe_signals.refund_recorded)
def send_refund_email(sender, order, amount, fully_refunded, **kwargs):
    """Tell the customer that (some or all of) their order has been refunded"""
    _, reply_to = get_email_settings()
    refunded = "has been refunded" if fully_refunded else "has been partly refunded"
    email = Email(
        order_subject(order, f" {refunded}"),
        [
            Paragraph(
                f"We have refunded £{amount:.2f} to the card (or other payment method) "
                "you used for this order. It can take 5-10 working days to appear on "
                "your statement."
            ),
            Link("View the status of your order", order_status_url(order)),
        ],
        footer=customer_footer(),
    )
    send_email(email, [order.email], reply_to)


@receiver(stripe_signals.dispute_created)
@receiver(stripe_signals.dispute_closed)
def send_dispute_notification(sender, order, message, signal, **kwargs):
    """Tell the shop about a disputed payment"""
    notify_emails, reply_to = get_email_settings()
    if not notify_emails:
        return
    if signal is stripe_signals.dispute_created:
        about = ": payment disputed"
    else:
        about = ": dispute closed"
    email = Email(
        order_subject(order, about),
        [Paragraph(message), Link("View the order", order_admin_url(order))],
    )
    send_email(email, notify_emails, reply_to)


@receiver(stripe_signals.account_deauthorized)
def send_account_deauthorized_notification(sender, account_id, **kwargs):
    """Tell the shop that card payments can't be taken"""
    notify_emails, reply_to = get_email_settings()
    if not notify_emails:
        return
    email = Email(
        "PINS shop: Stripe account disconnected, card payments are unavailable",
        [
            Paragraph(
                f"The Stripe account {account_id} has been disconnected from the "
                "website, so the shop can't take card payments until a Stripe account "
                "is connected again. (If the connect page has been disabled, it needs "
                "to be enabled again.)"
            ),
            Link(
                "Connect a Stripe account",
                f"https://{settings.DOMAIN}{reverse('stripe-connect')}",
            ),
        ],
    )
    send_email(email, notify_emails, reply_to)


def _item_dispatch_note(order, item):
    """
    Who sends the item (or who it's collected from), for the shop's new order
    email: (the note, whether the shop needs to pass it on)
    """
    if not item.needs_shipping:
        return "no shipping needed", False
    if item.dispatcher is None:
        return "no dispatcher", True
    emailed = item.product is not None and item.product.product.notify_dispatcher
    by = "to be collected from" if order.is_collected else "to be sent by"
    note = format_html(
        "{} <strong>{}</strong> ({})",
        by,
        item.dispatcher_name,
        "emailed" if emailed else "not emailed",
    )
    return note, not emailed


def order_items_lines(order, items, notes=None):
    """
    An order's items ("2 x Mug", with each item's note if given), then its
    discount and total
    """
    if notes is None:
        lines = [f"{item.quantity} x {item.name}" for item in items]
    else:
        lines = [
            format_html("{} x {}: {}", item.quantity, item.name, note)
            for item, note in zip(items, notes)
        ]
    discount = order.discount_row
    totals = []
    if discount:
        totals.append(
            f"Discount code: {order.discount_code} (-£{-Decimal(discount['amount']):.2f})"
        )
        totals.append(f"Total: £{order.total:.2f} (including discount)")
    else:
        totals.append(f"Total: £{order.total:.2f}")
    return [Items(lines, title="Items:"), Paragraph("\n".join(totals))]


def shop_order_email(order):
    """
    The shop's new order email: the order's details, with each item's dispatcher,
    so the shop can pass on anything a dispatcher hasn't been emailed about
    """
    items = list(order.items.select_related("dispatcher"))
    dispatch_notes = [_item_dispatch_note(order, item) for item in items]
    notes = [note for note, _ in dispatch_notes]
    pass_on = [pass_on for _, pass_on in dispatch_notes]
    if order.status == order.Status.HOLD:
        paid = "Awaiting payment"
    elif order.amount_received >= order.total:
        paid = "Paid"
    else:
        paid = "Not paid"
    intro = f"A new shop order {order.ref} has been received ({paid.lower()})."
    if any(pass_on):
        intro += (
            "\nSome items' dispatchers haven't been emailed (or there isn't one): "
            "please pass these on."
        )
    blocks = [
        Paragraph(intro),
        Paragraph(
            f"Customer: {order.name} ({order.email})\n"
            f"Shipping method: {order.get_shipping_method_display()}"
        ),
        *customer_details_blocks(order),
        *order_items_lines(order, items, notes),
        Link("View the order", order_admin_url(order)),
    ]
    return Email(order_subject(order, ": new order"), blocks)


OUTSIDE_UK_WARNING = (
    "OUTSIDE THE UK: check that shipping has been pre-arranged with the customer "
    "and any extra costs have been paid before shipping."
)


def customer_details_blocks(order):
    """
    For the shop's and dispatchers' emails: the customer's mobile number, and
    for delivery, the address (flagged if it's outside the UK) and safe place
    """
    blocks = []
    if order.phone:
        blocks.append(Paragraph(f"Mobile number: {order.phone}"))
    if order.needs_delivery:
        blocks.append(Paragraph(f"Shipping address:\n{order.shipping_address}"))
        if order.outside_uk:
            blocks.append(Paragraph(format_html("<strong>{}</strong>", OUTSIDE_UK_WARNING)))
        if order.safe_place:
            blocks.append(Paragraph(f"Safe place: {order.safe_place}"))
    return blocks


def notify_dispatchers(order):
    """
    Once the transaction has committed (when the order's items have been
    created), email dispatchers about their items to send (or hand over, for
    collection), for products that are set to email the dispatcher
    """

    def _notify():
        _, reply_to = get_email_settings()
        items = order.items.filter(
            shipping_status=OrderItem.TO_SEND, dispatcher__isnull=False
        ).select_related("dispatcher")
        by_dispatcher = {}
        for item in items:
            if item.product is not None and item.product.product.notify_dispatcher:
                by_dispatcher.setdefault(item.dispatcher, []).append(item)
        if order.is_collected:
            about = ": items to be collected"
            title = f"PINS shop order {order.ref} has items to be collected from you:"
            mark = "Mark the items as collected once they've been picked up"
        else:
            about = ": items to send"
            title = f"PINS shop order {order.ref} has items for you to send:"
            mark = "Mark the items as sent once you've sent them"
        for dispatcher, dispatcher_items in by_dispatcher.items():
            customer = f"Customer: {order.name} ({order.email})"
            if not order.needs_delivery:
                customer += f"\nShipping method: {order.get_shipping_method_display()}"
            blocks = [
                Items(
                    [f"{item.quantity} x {item.name}" for item in dispatcher_items],
                    title=title,
                ),
                Paragraph(customer),
                *customer_details_blocks(order),
                Link(mark, f"https://{settings.DOMAIN}{reverse('shop_dispatch:index')}"),
            ]
            _send_email_now(
                Email(order_subject(order, about), blocks), [dispatcher.email], reply_to
            )

    transaction.on_commit(_notify)


@receiver(status_changed)
def notify_dispatchers_when_paid(sender, order, new_status, old_status, **kwargs):
    """An order that was waiting for payment (e.g. on hold) has been paid"""
    if new_status == order.Status.PROCESSING:
        notify_dispatchers(order)


@receiver(status_changed)
def send_notification(sender, order, new_status, old_status, **kwargs):
    """
    Send notification to customer when order is moved to completed.
    """
    if new_status in [order.Status.COMPLETED, order.Status.PROCESSING]:
        _, reply_to = get_email_settings()
        if new_status == order.Status.COMPLETED:
            subject = order_subject(order, " is complete")
            blocks = [Paragraph(f"Order {order.ref} is now complete.")]
        else:
            # paid after it was placed (e.g. on hold)
            subject = order_subject(order, " is being processed")
            blocks = [
                Paragraph(
                    f"Payment for order {order.ref} has been received, and it's "
                    "being processed."
                ),
                *collection_blocks(order),
            ]
        blocks.append(Link("View the status of your order", order_status_url(order)))
        send_email(
            Email(subject, blocks, footer=customer_footer()), [order.email], reply_to
        )


def collection_blocks(order):
    """For collection orders, how to collect"""
    if not order.is_collected:
        return []
    return [
        Paragraph(
            "This order is to be collected by prior arrangement with PINS. Please "
            "contact PINS to confirm when it will be ready and where to collect it."
        )
    ]


def customer_order_email(order):
    """The customer's email when their order is placed: what they ordered"""
    if order.status == order.Status.HOLD:
        intro = "Thank you for your order! It will be processed once payment has been received."
    elif order.status == order.Status.COMPLETED:
        # e.g. nothing in the order needs shipping
        intro = "Thank you for your order! It's complete: nothing needs sending."
    elif order.is_collected:
        intro = "Thank you for your order! It's being processed."
    else:
        intro = (
            "Thank you for your order! It's being processed, and we'll email you "
            "when the items are sent."
        )
    blocks = [
        Paragraph(intro),
        *(collection_blocks(order) if order.status == order.Status.PROCESSING else []),
        *order_items_lines(order, list(order.items.all())),
        Link("View the status of your order", order_status_url(order)),
    ]
    return Email(order_subject(order, " has been received"), blocks, footer=customer_footer())


@receiver(post_save, sender=ProductImage)
@receiver(post_save, sender=ProductVariant)
def file_shop_images(sender, instance, **kwargs):
    """
    Product and variant images go in the Shop collection, so shop admins (who
    can only see that collection) can see and choose them
    """
    file_in_shop_collection(instance.image)


@receiver(post_save, sender=Order)
def send_new_order_notifications(sender, instance, created, **kwargs):
    """
    Send notification to customer when order is first created
    """
    if created:
        notify_emails, reply_to = get_email_settings()
        # Once the transaction has committed, when the order's items have been
        # created
        transaction.on_commit(
            lambda: _send_email_now(customer_order_email(instance), [instance.email], reply_to)
        )
        if notify_emails:
            transaction.on_commit(
                lambda: _send_email_now(shop_order_email(instance), notify_emails, reply_to)
            )

        if instance.status == instance.Status.PROCESSING:
            # Paid when it was created
            notify_dispatchers(instance)


@receiver(items_shipped)
def send_items_shipped_email(sender, order, items, **kwargs):
    """
    Tell the customer which items have been shipped (or collected), and which
    are still to come
    """
    _, reply_to = get_email_settings()
    done = "collected" if order.is_collected else "shipped"
    to_come = list(order.items.filter(shipping_status=OrderItem.TO_SEND))
    item_ids = {item.id for item in items}
    already_done = [
        item
        for item in order.items.filter(shipping_status=OrderItem.SHIPPED)
        if item.id not in item_ids
    ]
    if to_come:
        subject = order_subject(order, f" has been partly {done}")
    else:
        subject = order_subject(order, f" has been {done}")

    def item_list(items, title):
        return Items([f"{item.quantity} x {item.name}" for item in items], title=title)

    blocks = [item_list(items, f"These items from order {order.ref} have been {done}:")]
    if already_done:
        blocks.append(item_list(already_done, f"These items had already been {done}:"))
    if to_come:
        blocks.append(item_list(to_come, f"Still to be {done}:"))
    blocks.append(Link("View the status of your order", order_status_url(order)))
    send_email(Email(subject, blocks, footer=customer_footer()), [order.email], reply_to)


def adjust_stock(variant, change):
    """
    Add change (a quantity of the variant, which may be negative) to its stock:
    the variant's own stock, or the product's if its variants share stock (in
    single items, so change x the variant's pack size); nothing if the product
    has no stock limit. Uses an F expression so
    concurrent updates can't overwrite each other, then refreshes the in-memory
    stock value.
    """
    if variant.product.unlimited_stock:
        # (no stock is counted)
        return
    holder = variant.stock_holder
    type(holder).objects.filter(pk=holder.pk).update(
        stock=F("stock") + change * variant.items_per_unit
    )
    holder.refresh_from_db(fields=["stock"])


@receiver(post_init, sender=BasketItem)
def post_init_item(sender, instance, **kwargs):
    # Remember current quantity on the instance
    instance._current_quantity = 0 if instance.pk is None else instance.quantity


@receiver(post_save, sender=BasketItem)
def post_save_item(sender, instance, **kwargs):
    if instance.product:
        quantity_diff = instance._current_quantity - instance.quantity
        # positive diff means items have been taken out of basket, so add to stock
        if quantity_diff:
            adjust_stock(instance.product, quantity_diff)
    # Update the remembered quantity, so saving this instance again doesn't
    # adjust stock again
    instance._current_quantity = instance.quantity


@receiver(post_delete, sender=BasketItem)
def post_delete_basket_item(sender, instance, **kwargs):
    if instance.product:
        adjust_stock(instance.product, instance.quantity)


@receiver(post_delete, sender=Basket)
def post_delete_item(sender, instance, **kwargs):
    if "basket_id" in instance.extra:
        matching_order = Order.objects.filter(
            _extra__basket_id=instance.extra["basket_id"]
        )
        if matching_order.exists():
            order = matching_order.first()
            # basket deleted post-order creation, items from basket have been replaced
            # in stock, so we need to update the stock based on the order items
            for item in order.get_items():
                if item.product:
                    adjust_stock(item.product, -item.quantity)


@receiver(pre_delete, sender=ProductVariant)
def protect_ordered_variants(sender, instance, **kwargs):
    """
    Don't delete variants that have been ordered (salesman similarly protects
    variants that are in baskets). This includes when a product or category page
    is deleted; deletion happens in a transaction, so nothing is deleted.
    """
    order_items = order_items_for_variants([instance.id])
    if order_items.exists():
        raise ProtectedError(
            f"Cannot delete '{instance}' because it has been ordered.",
            set(order_items),
        )



# The activity log (see activity.py): what happens to orders outside our admin
# views (from checkout and the Stripe webhook), or in both


@receiver(post_save, sender=Order)
def log_order_placed(sender, instance, created, **kwargs):
    if created:
        activity.log_order(instance, activity.ORDER_PLACED, total=activity.amount_data(instance.total))


@receiver(post_save, sender=OrderPayment)
def log_order_paid(sender, instance, created, **kwargs):
    # (refunds are recorded as negative payments, and logged when recorded)
    if created and instance.amount > 0:
        activity.log_order(
            instance.order, activity.ORDER_PAID, amount=activity.amount_data(instance.amount)
        )


@receiver(stripe_signals.refund_recorded)
def log_refund(sender, order, amount, fully_refunded, **kwargs):
    # from the orders admin (with its user), or from the Stripe dashboard (by the
    # webhook, with no user)
    activity.log_order(
        order,
        activity.ORDER_REFUNDED,
        amount=activity.amount_data(amount),
        fully_refunded=fully_refunded,
    )


@receiver(stripe_signals.dispute_created)
def log_dispute_created(sender, order, message, **kwargs):
    activity.log_order(order, activity.ORDER_DISPUTED, message=message)


@receiver(stripe_signals.dispute_closed)
def log_dispute_closed(sender, order, message, **kwargs):
    activity.log_order(order, activity.ORDER_DISPUTE_CLOSED, message=message)


# The shop settings are edited in Wagtail's settings view, which logs just
# "Edited": add what changed to that entry (if anything did). The changes are
# worked out when the settings are saved (just before the entry is logged), by
# settings pk.
_settings_changes = {}


@receiver(pre_save, sender=ShopSettings)
def remember_shop_settings(sender, instance, **kwargs):
    instance._previous = ShopSettings.objects.filter(pk=instance.pk).first() if instance.pk else None


@receiver(post_save, sender=ShopSettings)
def remember_shop_settings_changes(sender, instance, created, **kwargs):
    previous = getattr(instance, "_previous", None)
    _settings_changes.pop(instance.pk, None)
    if previous is None:
        return
    changes = []
    for field in ShopSettings._meta.concrete_fields:
        if field.primary_key:
            continue
        old, new = getattr(previous, field.attname), getattr(instance, field.attname)
        if old != new:
            changes.append(
                f"{str(field.verbose_name).capitalize()}: "
                f"{activity.settings_value(field, old)} → {activity.settings_value(field, new)}"
            )
    if changes:
        _settings_changes[instance.pk] = changes


@receiver(pre_save, sender=ModelLogEntry)
def add_shop_settings_changes(sender, instance, **kwargs):
    if (
        instance.pk is None
        and instance.action == "wagtail.edit"
        and instance.content_type.model_class() is ShopSettings
    ):
        changes = _settings_changes.pop(int(instance.object_id), None)
        if changes:
            instance.action = activity.SETTINGS_EDITED
            instance.data = {**(instance.data or {}), "changes": changes}
