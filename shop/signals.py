# signals.py
from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models.signals import post_delete, post_init, post_save
from django.dispatch import receiver
from django.urls import reverse

from salesman.core.utils import get_salesman_model
from salesman.orders.signals import status_changed

from .models import ShopSettings, ProductVariant


BasketItem = get_salesman_model("BasketItem")
Basket = get_salesman_model("Basket")
Order = get_salesman_model("Order")


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


@receiver(status_changed)
def send_notification(sender, order, new_status, old_status, **kwargs):
    """
    Send notification to customer when order is moved to completed.
    """
    status_url = f'{settings.DOMAIN}{reverse("shop:order_status", args=(order.token,))}'
    if new_status in [order.Status.COMPLETED, order.Status.PROCESSING]:
        reply_to, _ = get_email_settings()
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

        email = EmailMessage(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.email],
            reply_to=reply_to,
        )
        email.send()


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

        email = EmailMessage(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [instance.email],
            reply_to=reply_to,
        )
        email.send()

        if notify_emails:
            subject = f"New shop order '{instance.ref}'"
            message = "A new shop order has been received."
            email = EmailMessage(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                notify_emails,
                reply_to=reply_to,
            )
            email.send()


@receiver(post_init, sender=BasketItem)
def post_init_item(sender, instance, **kwargs):
    # Remember current quantity on the instance
    instance._current_quantity = 0 if instance.pk is None else instance.quantity


@receiver(post_save, sender=BasketItem)
def post_save_item(sender, instance, **kwargs):
    if instance.product:
        quantity_diff = instance._current_quantity - instance.quantity
        # positive diff means items have been taken out of basket, so add to stock
        instance.product.stock += quantity_diff
        instance.product.save()


@receiver(post_delete, sender=BasketItem)
def post_delete_basket_item(sender, instance, **kwargs):
    if instance.product:
        instance.product.stock += instance.quantity
        instance.product.save()


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
                item.product.stock -= item.quantity
                item.product.save()


@receiver(post_save, sender=ProductVariant)
def update_price(sender, instance, **kwargs):
    if instance.price is None or instance.price == "":
        instance.price = instance.product.price
        instance.save()
