# signals.py
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import F
from django.db.models import ProtectedError
from django.db.models.signals import post_delete, post_init, post_save, pre_delete
from django.dispatch import receiver
from django.urls import reverse

from salesman.core.utils import get_salesman_model
from salesman.orders.signals import status_changed
from salesman_stripe_connect import signals as stripe_signals

from .models import (
    OrderItem,
    ProductVariant,
    ShopSettings,
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


def _send_email_now(subject, message, to, reply_to):
    """
    Failures are logged rather than raised, so that a failed email can't fail
    the request that created or updated the order (e.g. the Stripe webhook).
    """
    email = EmailMessage(
        subject, message, settings.DEFAULT_FROM_EMAIL, to, reply_to=reply_to
    )
    try:
        email.send()
    except Exception:
        logger.exception("Error sending email '%s' to %s", subject, to)


def send_email(subject, message, to, reply_to):
    """Send an email once the current transaction has committed"""
    transaction.on_commit(lambda: _send_email_now(subject, message, to, reply_to))


def order_status_url(order):
    return f'https://{settings.DOMAIN}{reverse("shop:order_status", args=(order.token,))}'


@receiver(stripe_signals.refund_recorded)
def send_refund_email(sender, order, amount, fully_refunded, **kwargs):
    """Tell the customer that (some or all of) their order has been refunded"""
    _, reply_to = get_email_settings()
    if fully_refunded:
        subject = f"Order '{order.ref}' has been refunded"
    else:
        subject = f"Order '{order.ref}' has been partially refunded"
    message = (
        f"We have refunded £{amount:.2f} to the card (or other payment method) you "
        "used for this order. It can take 5-10 working days to appear on your "
        "statement.\n"
        f"View the status of your order: {order_status_url(order)}"
    )
    send_email(subject, message, [order.email], reply_to)


@receiver(stripe_signals.dispute_created)
@receiver(stripe_signals.dispute_closed)
def send_dispute_notification(sender, order, message, signal, **kwargs):
    """Tell the shop about a disputed payment"""
    notify_emails, reply_to = get_email_settings()
    if not notify_emails:
        return
    if signal is stripe_signals.dispute_created:
        subject = f"Payment for shop order '{order.ref}' has been disputed"
    else:
        subject = f"Dispute for shop order '{order.ref}' closed"
    send_email(subject, message, notify_emails, reply_to)


@receiver(stripe_signals.account_deauthorized)
def send_account_deauthorized_notification(sender, account_id, **kwargs):
    """Tell the shop that card payments can't be taken"""
    notify_emails, reply_to = get_email_settings()
    if not notify_emails:
        return
    subject = "Stripe account disconnected: shop card payments are unavailable"
    message = (
        f"The Stripe account {account_id} has been disconnected from the website, so "
        "the shop can't take card payments until a Stripe account is connected "
        f"again, at https://{settings.DOMAIN}{reverse('stripe-connect')}\n"
        "(If the connect page has been disabled, it needs to be enabled again.)"
    )
    send_email(subject, message, notify_emails, reply_to)


def _item_dispatch_note(item):
    """Who sends the item, for the shop's new order email"""
    if not item.needs_shipping:
        return "no shipping needed"
    if item.dispatcher is None:
        return "no dispatcher"
    emailed = item.product is not None and item.product.product.notify_dispatcher
    return f"{item.dispatcher_name} ({'emailed' if emailed else 'not emailed'})"


def shop_order_message(order):
    """
    The shop's new order email: the order's details, with each item's dispatcher,
    so the shop can pass on anything a dispatcher hasn't been emailed about
    """
    items = list(order.items.select_related("dispatcher"))
    notes = [_item_dispatch_note(item) for item in items]
    if order.status == order.Status.HOLD:
        paid = "Awaiting payment"
    elif order.amount_received >= order.total:
        paid = "Paid"
    else:
        paid = "Not paid"
    lines = [f"A new shop order '{order.ref}' has been received ({paid.lower()})."]
    if any(note.endswith("(not emailed)") or note == "no dispatcher" for note in notes):
        lines.append(
            "Some items' dispatchers haven't been emailed (or there isn't one): "
            "please pass these on."
        )
    lines += ["", f"Customer: {order.name} ({order.email})"]
    lines.append(f"Shipping method: {order.get_shipping_method_display()}")
    if order.needs_delivery:
        lines += ["Shipping address:", order.shipping_address]
    lines += ["", "Items:"]
    lines += [
        f"- {item.quantity} x {item.name}: {note}" for item, note in zip(items, notes)
    ]
    lines.append("")
    discount = order.discount_row
    if discount:
        lines.append(
            f"Discount code: {order.discount_code} (-£{-Decimal(discount['amount']):.2f})"
        )
        lines.append(f"Total: £{order.total:.2f} (including discount)")
    else:
        lines.append(f"Total: £{order.total:.2f}")
    admin_url = reverse("shop_order_modeladmin_edit", args=(order.pk,))
    lines += ["", f"View the order: https://{settings.DOMAIN}{admin_url}"]
    return "\n".join(lines)


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
            to_do, subject = "hand over (for collection)", "items to hand over"
        else:
            to_do, subject = "send", "items to send"
        for dispatcher, dispatcher_items in by_dispatcher.items():
            lines = [f"Shop order '{order.ref}' has items for you to {to_do}:"]
            lines += [f"- {item.quantity} x {item.name}" for item in dispatcher_items]
            lines += ["", f"Customer: {order.name} ({order.email})"]
            if order.needs_delivery:
                lines += ["Shipping address:", order.shipping_address]
            else:
                lines += [f"Shipping method: {order.get_shipping_method_display()}"]
            _send_email_now(
                f"Shop order '{order.ref}': {subject}",
                "\n".join(lines),
                [dispatcher.email],
                reply_to,
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
    status_url = order_status_url(order)
    if new_status in [order.Status.COMPLETED, order.Status.PROCESSING]:
        _, reply_to = get_email_settings()
        if new_status == order.Status.COMPLETED:
            subject = f"Order '{order.ref}' is completed"
            message = (
                "Thank you for your order! Your order is now complete.\n"
                f"View the status of your order: {status_url}"
            )

        elif new_status == order.Status.PROCESSING:
            subject = f"Order '{order.ref}' is being processed"
            message = (
                "Thank you for your order!  Your order is being processed.\n"
                f"View the status of your order: {status_url}"
            )

        send_email(subject, message, [order.email], reply_to)


@receiver(post_save, sender=Order)
def send_new_order_notifications(sender, instance, created, **kwargs):
    """
    Send notification to customer when order is first created
    """
    status_url = order_status_url(instance)
    if created:
        notify_emails, reply_to = get_email_settings()

        subject = f"Order '{instance.ref}' has been received"
        if instance.status == instance.Status.HOLD:
            message = (
                "Thank you for your order! Your order will be completed when payment has been received.\n"
                f"View the status of your order: {status_url}"
            )
        elif instance.status == instance.Status.COMPLETED:
            # e.g. nothing in the order needs shipping
            message = (
                "Thank you for your order! Your order is complete.\n"
                f"View the status of your order: {status_url}"
            )
        else:
            message = (
                "Thank you for your order! Your order is being processed.\n"
                f"View the status of your order: {status_url}"
            )

        send_email(subject, message, [instance.email], reply_to)

        if notify_emails:
            # Once the transaction has committed, when the order's items have
            # been created
            subject = f"New shop order '{instance.ref}'"
            transaction.on_commit(
                lambda: _send_email_now(
                    subject, shop_order_message(instance), notify_emails, reply_to
                )
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
    if to_come:
        subject = f"Part of order '{order.ref}' has been {done}"
    else:
        subject = f"Order '{order.ref}' has been {done}"
    lines = [f"These items from your order have been {done}:"]
    lines += [f"- {item.quantity} x {item.name}" for item in items]
    if to_come:
        lines += ["", f"Still to be {done}:"]
        lines += [f"- {item.quantity} x {item.name}" for item in to_come]
    lines += ["", f"View the status of your order: {order_status_url(order)}"]
    send_email(subject, "\n".join(lines), [order.email], reply_to)


def adjust_stock(variant, change):
    """
    Add change (a quantity of the variant, which may be negative) to its stock:
    the variant's own stock, or the product's if its variants share stock (in
    single items, so change x the variant's pack size). Uses an F expression so
    concurrent updates can't overwrite each other, then refreshes the in-memory
    stock value.
    """
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

