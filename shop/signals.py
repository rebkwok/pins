# signals.py
import logging

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

from .models import ProductVariant, ShopSettings, order_items_for_variants


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


def send_email(subject, message, to, reply_to):
    """
    Send an email once the current transaction has committed.
    Failures are logged rather than raised, so that a failed email can't
    fail the request that created or updated the order (e.g. the Stripe webhook).
    """
    email = EmailMessage(
        subject, message, settings.DEFAULT_FROM_EMAIL, to, reply_to=reply_to
    )

    def _send():
        try:
            email.send()
        except Exception:
            logger.exception("Error sending email '%s' to %s", subject, to)

    transaction.on_commit(_send)


@receiver(status_changed)
def send_notification(sender, order, new_status, old_status, **kwargs):
    """
    Send notification to customer when order is moved to completed.
    """
    status_url = f'{settings.DOMAIN}{reverse("shop:order_status", args=(order.token,))}'
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
    status_url = (
        f'{settings.DOMAIN}{reverse("shop:order_status", args=(instance.token,))}'
    )
    if created:
        notify_emails, reply_to = get_email_settings()

        subject = f"Order '{instance.ref}' has been received"
        if instance.status == instance.Status.HOLD:
            message = (
                "Thank you for your order! Your order will be completed when payment has been received.\n"
                f"View the status of your order: {status_url}"
            )
        else:
            message = (
                "Thank you for your order! Your order is being processed.\n"
                f"View the status of your order: {status_url}"
            )

        send_email(subject, message, [instance.email], reply_to)

        if notify_emails:
            subject = f"New shop order '{instance.ref}'"
            message = "A new shop order has been received."
            send_email(subject, message, notify_emails, reply_to)


def adjust_stock(variant, change):
    """
    Add change (which may be negative) to the variant's stock. Uses an F
    expression so concurrent updates can't overwrite each other, then refreshes
    the in-memory stock value.
    """
    ProductVariant.objects.filter(pk=variant.pk).update(stock=F("stock") + change)
    variant.refresh_from_db(fields=["stock"])


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

