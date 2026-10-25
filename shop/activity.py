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


# What changed when a shop item (or the shop settings) is edited

EDITED = "shop.edited"
SETTINGS_EDITED = "shop.settings.edited"

MAX_VALUE_LENGTH = 60


def display_value(field, value):
    """A form field's value, for a log message"""
    from django import forms

    if value in (None, ""):
        return "(blank)"
    if isinstance(field, forms.BooleanField):
        return "yes" if value else "no"
    if isinstance(field, forms.ModelMultipleChoiceField):
        objects = value if hasattr(value, "__iter__") else [value]
        names = [str(obj) if hasattr(obj, "pk") else str(field.queryset.filter(pk=obj).first() or obj) for obj in objects]
        return ", ".join(names) or "(none)"
    if isinstance(field, forms.ModelChoiceField):
        if not hasattr(value, "pk"):
            value = field.queryset.filter(pk=value).first() or value
        return str(value)
    if isinstance(field, forms.ChoiceField):
        return str(dict(field.choices).get(value, value))
    if isinstance(field, forms.DecimalField):
        return gbp(value)
    return Truncator(str(value)).chars(MAX_VALUE_LENGTH)


def is_long_text(field):
    """Rich text or long text, which is described as just "changed" """
    from django import forms

    widget = field.widget
    return isinstance(widget, forms.Textarea) or "RichText" in type(widget).__name__ or "Draftail" in type(widget).__name__


def field_changes(form):
    """The changed fields of a form (not its formsets), e.g. "Price: £10.00 → £12.00" """
    changes = []
    data = getattr(form, "cleaned_data", {})
    for name in form.changed_data:
        if name in ("stock_shown", "ORDER", "DELETE", "id") or name not in form.fields:
            continue
        field = form.fields[name]
        label = str(field.label or name.replace("_", " ").capitalize())
        if name == "stock" and "stock_shown" in form.fields:
            # stock is changed relative to the stock shown (RelativeStockFormMixin)
            change = (data.get("stock") or 0) - (data.get("stock_shown") or form.initial.get("stock") or 0)
            if change:
                changes.append(f"{label}: {change:+d}")
            continue
        if is_long_text(field):
            # (rich text's submitted value never matches its initial value
            # exactly, so compare the values that would be stored)
            if str(form.initial.get(name) or "").strip() != str(data.get(name) or "").strip():
                changes.append(f"{label} changed")
            continue
        old = display_value(field, form.initial.get(name, field.initial))
        new = display_value(field, data.get(name))
        if old != new:
            changes.append(f"{label}: {old} → {new}")
    return changes


def item_name(form):
    """A formset item's name (e.g. a variant's), or for a new one, its form's names"""
    instance = form.instance
    if instance.pk:
        # its name before this edit (the form has changed the instance)
        instance = type(instance).objects.filter(pk=instance.pk).first() or instance
    if instance.pk and hasattr(instance, "variant_full_name"):
        # a variant, on its product's page: just its own name
        return instance.variant_full_name() or "(no name)"
    try:
        return str(instance)
    except Exception:
        # e.g. a new variant, whose name includes its product's (not set yet)
        data = getattr(form, "cleaned_data", {})
        names = [str(data[key]) for key in ("variant_name", "colour", "size", "title", "name") if data.get(key)]
        return ", ".join(names)


def form_changes(form):
    """
    What changed in an edit form, including its formsets (e.g. a product's
    variants and images): ["Price: £10.00 → £12.00", "Added variant: Large",
    "Variant Small: Stock: +5"]
    """
    changes = field_changes(form)
    for formset in getattr(form, "formsets", {}).values():
        # e.g. "variant", "image" (on the product's page)
        kind = str(formset.model._meta.verbose_name).removeprefix("product ")
        for child in formset.forms:
            if not getattr(child, "cleaned_data", None) and not child.has_changed():
                continue
            name = item_name(child) if child.instance.pk else ""
            if formset.can_delete and formset._should_delete_form(child):
                if child.instance.pk:
                    changes.append(f"Removed {kind}: {name}")
                continue
            if child.instance.pk is None:
                if child.has_changed():
                    new_name = item_name(child)
                    changes.append(f"Added {kind}" + (f": {new_name}" if new_name else ""))
                continue
            changes += [f"{kind.capitalize()} {name}: {change}" for change in field_changes(child)]
    return changes


class Edited(ShopLogFormatter):
    label = "Edit (with changes)"

    def format_message(self, log_entry):
        return f"Edited: {'; '.join(self.data(log_entry, 'changes', []))}"


SHOP_LOG_ACTIONS[EDITED] = Edited


class SettingsEdited(Edited):
    label = "Shop settings edited"


SHOP_LOG_ACTIONS[SETTINGS_EDITED] = SettingsEdited


def settings_value(field, value):
    """A setting's value, for a log message"""
    from django.db import models

    if value in (None, ""):
        return "(blank)"
    if isinstance(field, models.DecimalField):
        return gbp(value)
    return Truncator(str(value)).chars(MAX_VALUE_LENGTH)
