"""
The shop's activity log: who did what to orders, dispatchers and the shop's
setup, in Wagtail's audit log (alongside its own entries for creating, editing
and deleting products, categories and so on).

Each action is registered (see wagtail_hooks.register_shop_log_actions) with a
formatter that writes its message from the entry's data, e.g. "Marked shipped:
2 × Podenco mug". Entries are logged with wagtail.log_actions.log, which
records the admin user (from Wagtail's log context, so actions taken in the
admin are attributed to whoever took them); entries logged outside the admin
(e.g. from the Stripe webhook) have no user, and are shown as "system".
"""

from decimal import Decimal

from django.utils.text import Truncator
from wagtail.log_actions import LogFormatter, log


ORDER_PLACED = "shop.order.placed"
ORDER_PAID = "shop.order.paid"
ORDER_SHIPPED = "shop.order.shipped"
ORDER_NOT_SENT = "shop.order.not_sent"
ORDER_COMPLETED = "shop.order.completed"
ORDER_CANCELLED = "shop.order.cancelled"
ORDER_REFUNDED = "shop.order.refunded"
ORDER_NOTE = "shop.order.note"
ORDER_DISPUTED = "shop.order.disputed"
ORDER_DISPUTE_CLOSED = "shop.order.dispute_closed"
CATEGORY_REORDERED = "shop.category.reordered"
DISPATCHER_ADDED = "shop.dispatcher.added"
DISPATCHER_REMOVED = "shop.dispatcher.removed"


def gbp(amount):
    """e.g. £5.00 (shoptags.gbp, which can't be imported here, as it imports the models)"""
    return f"£{Decimal(amount or 0):,.2f}"


def item_descriptions(items):
    """e.g. ["2 × Podenco mug", "1 × PINS T-shirt - Black, S"]"""
    return [f"{item.quantity} × {item.name}" for item in items]


def log_order(order, action, user=None, **data):
    return log(order, action, user=user, data=data)


def log_items(order, action, items, user=None):
    return log_order(
        order,
        action,
        user=user,
        items=item_descriptions(items),
        collected=order.is_collected,
    )


class ShopLogFormatter(LogFormatter):
    def data(self, log_entry, key, default=""):
        return (log_entry.data or {}).get(key, default)


class OrderPlaced(ShopLogFormatter):
    label = "Order placed"

    def format_message(self, log_entry):
        return f"Order placed ({gbp(self.data(log_entry, 'total'))})"


class OrderPaid(ShopLogFormatter):
    label = "Order paid"

    def format_message(self, log_entry):
        return f"Paid {gbp(self.data(log_entry, 'amount'))}"


class ItemsFormatter(ShopLogFormatter):
    def format_message(self, log_entry):
        return f"{self.prefix(log_entry)}: {', '.join(self.data(log_entry, 'items', []))}"


class ItemsShipped(ItemsFormatter):
    label = "Items shipped or collected"

    def prefix(self, log_entry):
        return "Marked collected" if self.data(log_entry, "collected", False) else "Marked shipped"


class ItemsNotSent(ItemsFormatter):
    label = "Items won't be sent"

    def prefix(self, log_entry):
        return "Marked won't be sent"


class OrderRefunded(ShopLogFormatter):
    label = "Order refunded"

    def format_message(self, log_entry):
        amount = gbp(self.data(log_entry, "amount"))
        if self.data(log_entry, "fully_refunded", False):
            return f"Refunded {amount} (the whole order)"
        return f"Refunded {amount} (part of the order)"


class OrderNoteAdded(ShopLogFormatter):
    label = "Note added"

    def format_message(self, log_entry):
        return f"Added a note: {Truncator(self.data(log_entry, 'message')).chars(100)}"


class MessageFormatter(ShopLogFormatter):
    """The entry's message is in its data (e.g. a dispute's details)"""

    def format_message(self, log_entry):
        return self.data(log_entry, "message")


class OrderDisputed(MessageFormatter):
    label = "Payment disputed"


class OrderDisputeClosed(MessageFormatter):
    label = "Dispute closed"


class CategoryReordered(ShopLogFormatter):
    label = "Products reordered"

    def format_message(self, log_entry):
        return (
            f"Moved {self.data(log_entry, 'product')} to position "
            f"{self.data(log_entry, 'position')}"
        )


SHOP_LOG_ACTIONS = {
    CATEGORY_REORDERED: CategoryReordered,
    ORDER_PLACED: OrderPlaced,
    ORDER_PAID: OrderPaid,
    ORDER_SHIPPED: ItemsShipped,
    ORDER_NOT_SENT: ItemsNotSent,
    ORDER_REFUNDED: OrderRefunded,
    ORDER_NOTE: OrderNoteAdded,
    ORDER_DISPUTED: OrderDisputed,
    ORDER_DISPUTE_CLOSED: OrderDisputeClosed,
}

# Actions with a fixed message: (label, message)
SHOP_SIMPLE_LOG_ACTIONS = {
    ORDER_COMPLETED: ("Order completed", "Marked completed"),
    ORDER_CANCELLED: ("Order cancelled", "Cancelled"),
    DISPATCHER_ADDED: ("Dispatcher added", "Added as a dispatcher"),
    DISPATCHER_REMOVED: ("Dispatcher removed", "Removed as a dispatcher"),
}


def register(actions):
    """Register the shop's log actions (from the register_log_actions hook)"""
    for action, formatter in SHOP_LOG_ACTIONS.items():
        actions.register_action(action)(formatter)
    for action, (label, message) in SHOP_SIMPLE_LOG_ACTIONS.items():
        actions.register_action(action, label, message)


def amount_data(amount):
    """An amount for an entry's data (which is stored as JSON)"""
    return str(Decimal(amount).quantize(Decimal("0.01")))
