# signals.py
from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver

from salesman.orders.signals import status_changed


@receiver(status_changed)
def send_notification(sender, order, new_status, old_status, **kwargs):
    """
    Send notification to customer when order is moved to on hold (pending payment) or completed.
    """
    if new_status == order.Status.COMPLETED:
        subject = f"Order '{order}' is completed"
        message = "Thank you for your order!"
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [order.email])

    elif new_status == order.Status.HOLD:
        subject = f"Order '{order}' is processing"
        message = "Thank you for your order! Your order will be completed when payment has been received."
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [order.email])
