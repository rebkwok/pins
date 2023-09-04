# signals.py
from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver
from django.db.models.signals import post_save

from salesman.core.utils import get_salesman_model
from salesman.orders.signals import status_changed


Order = get_salesman_model("Order")


@receiver(status_changed)
def send_notification(sender, order, new_status, old_status, **kwargs):
    """
    Send notification to customer when order is moved to completed.
    """
    if new_status == order.Status.COMPLETED:
        subject = f"Order '{order.ref}' is completed"
        message = "Thank you for your order! Your order is now complete."
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [order.email]) 
    elif new_status == order.Status.PROCESSING:
        subject = f"Order '{order.ref}' is being processed"
        message = "Thank you for your order!  Your order is being processed."
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [order.email])        


@receiver(post_save, sender=Order)
def create_profile(sender, instance, created, **kwargs):
    """
    Send notification to customer when order is first created and set to on hold (pending payment)
    """
    if created and instance.status == instance.Status.HOLD:
        subject = f"Order '{instance.ref}' has been received"
        message = "Thank you for your order! Your order will be completed when payment has been received."
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [instance.email])
