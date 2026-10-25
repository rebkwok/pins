"""The shop's activity log (activity.py): what's logged, by whom, and its messages"""

import html
import json
from decimal import Decimal

import pytest
from django.urls import reverse
from model_bakery import baker
from salesman.core.utils import get_salesman_model
from wagtail.log_actions import registry as log_registry
from wagtail.models import ModelLogEntry

from salesman_stripe_connect import signals as stripe_signals

from .. import activity
from ..models import DISPATCHERS_GROUP, OrderItem, Product
from ..payment import PayByStripe
from .factories import PRODUCT_FORM_DEFAULTS

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")


@pytest.fixture
def admin(client):
    user = baker.make("auth.User", is_superuser=True, is_staff=True, first_name="Ann", last_name="Admin")
    client.force_login(user)
    return user


@pytest.fixture
def paid_order(order):
    order.status = Order.Status.PROCESSING
    order.save()
    order.pay(amount=order.total, transaction_id="pi_1", payment_method="stripe")
    return order


def entries(obj, action=None):
    logs = log_registry.get_logs_for_instance(obj).order_by("timestamp", "pk")
    return list(logs.filter(action=action) if action else logs)


def messages(obj):
    return [entry.message for entry in entries(obj)]


# Orders: placed and paid (at checkout, or from the Stripe webhook)


def test_order_placed_and_paid(paid_order):
    (placed,) = entries(paid_order, activity.ORDER_PLACED)
    assert placed.message == "Order placed (£20.00)"
    assert placed.user is None
    (paid,) = entries(paid_order, activity.ORDER_PAID)
    assert paid.message == "Paid £20.00"


def test_refund_logged_once(paid_order):
    # refunds are payments with negative amounts: logged as refunds, not payments
    PayByStripe.record_refund(paid_order, "re_1", Decimal("5.00"))
    PayByStripe.record_refund(paid_order, "re_1", Decimal("5.00"))
    assert len(entries(paid_order, activity.ORDER_PAID)) == 1
    (refund,) = entries(paid_order, activity.ORDER_REFUNDED)
    assert refund.message == "Refunded £5.00 (part of the order)"
    PayByStripe.record_refund(paid_order, "re_2", Decimal("15.00"))
    assert entries(paid_order, activity.ORDER_REFUNDED)[-1].message == "Refunded £15.00 (the whole order)"


def test_disputes(paid_order):
    stripe_signals.dispute_created.send(sender=None, order=paid_order, dispute=None, message="Disputed: fraudulent")
    stripe_signals.dispute_closed.send(sender=None, order=paid_order, dispute=None, message="The dispute was won.")
    assert messages(paid_order)[-2:] == ["Disputed: fraudulent", "The dispute was won."]


# Orders: our actions


def test_items_shipped_and_not_sent(paid_order, admin):
    item = paid_order.items.get()
    paid_order.mark_items_shipped([item], admin)
    (entry,) = entries(paid_order, activity.ORDER_SHIPPED)
    assert entry.user == admin
    # (the order fixture is collected)
    assert entry.message == f"Marked collected: 2 × {item.name}"
    paid_order.shipping_method = "deliver"
    paid_order.save()
    item.shipping_status = OrderItem.TO_SEND
    item.save()
    paid_order.mark_items_not_sent([item], admin)
    assert entries(paid_order, activity.ORDER_NOT_SENT)[0].message == f"Marked won't be sent: 2 × {item.name}"
    # nothing changed (already marked): nothing logged
    paid_order.mark_items_shipped([item], admin)
    assert len(entries(paid_order, activity.ORDER_SHIPPED)) == 1


def test_shipped_message_delivered(paid_order, admin):
    paid_order.shipping_method = "deliver"
    paid_order.save()
    item = paid_order.items.get()
    paid_order.mark_items_shipped([item], admin)
    assert entries(paid_order, activity.ORDER_SHIPPED)[0].message.startswith("Marked shipped: ")


def test_note_complete_and_cancel_from_admin(client, admin, paid_order):
    client.post(reverse("shop_orders:edit", args=(paid_order.pk,)), {"message": "Customer called " + "x" * 120})
    (note,) = entries(paid_order, activity.ORDER_NOTE)
    assert note.user == admin
    assert note.message.startswith("Added a note: Customer called x")
    assert note.message.endswith("…")
    paid_order.items.update(shipping_status=OrderItem.SHIPPED)
    paid_order.status = Order.Status.SHIPPED
    paid_order.save()
    client.post(reverse("shop_orders:complete", args=(paid_order.pk,)))
    assert entries(paid_order, activity.ORDER_COMPLETED)[0].message == "Marked completed"


def test_cancel_from_admin(client, admin, order):
    client.post(reverse("shop_orders:cancel", args=(order.pk,)))
    (entry,) = entries(order, activity.ORDER_CANCELLED)
    assert (entry.user, entry.message) == (admin, "Cancelled")


def test_order_page_activity(client, admin, paid_order):
    paid_order.mark_items_shipped(list(paid_order.items.all()), admin)
    content = " ".join(html.unescape(client.get(reverse("shop_orders:edit", args=(paid_order.pk,))).content.decode()).split())
    assert "<h2 class=\"w-h3\">Activity</h2>" in content
    # oldest first; checkout and the webhook have no user
    assert "<td>Customer / Stripe</td> <td>Order placed (£20.00)</td>" in content
    assert "<td>Ann Admin</td> <td>Marked collected: 2 ×" in content
    assert content.index("Order placed") < content.index("Marked collected")


def test_order_page_no_activity(client, admin, order):
    ModelLogEntry.objects.all().delete()
    content = client.get(reverse("shop_orders:edit", args=(order.pk,))).content.decode()
    assert "No activity yet." in content


# Dispatchers and the shop's setup


def test_dispatcher_added_and_removed(client, admin):
    user = baker.make("auth.User", first_name="Dee", last_name="Spatcher")
    client.post(reverse("shop_dispatchers:index"), {"user": user.pk})
    client.post(reverse("shop_dispatchers:index"), {"remove": user.pk})
    assert [(entry.user, entry.message) for entry in entries(user)] == [
        (admin, "Added as a dispatcher"),
        (admin, "Removed as a dispatcher"),
    ]
    assert not user.groups.filter(name=DISPATCHERS_GROUP).exists()


def test_category_products_reordered(client, admin, category):
    baker.make(Product, name="Mug", category=category)
    cup = baker.make(Product, name="Cup", category=category)
    url = reverse("shop_category_products_reorder", args=(category.pk, cup.pk))
    client.post(f"{url}?position=0")
    (entry,) = entries(category, activity.CATEGORY_REORDERED)
    assert (entry.user, entry.message) == (admin, "Moved Cup to position 1")


def test_formatters_without_data(order):
    # (e.g. an entry logged without data)
    entry = activity.log_order(order, activity.ORDER_PAID)
    assert entry.message == "Paid £0.00"
    assert activity.gbp(None) == "£0.00"


# What changed, when shop items and the shop settings are edited


def product_form_data(product, variants, **data):
    form = {
        "category": product.category.id,
        "name": product.name,
        "price": str(product.price),
        "description": json.dumps({"blocks": [], "entityMap": {}}),
        "live": "on",
        "requires_shipping": "on",
        **PRODUCT_FORM_DEFAULTS,
        "stock_shown": "0",
        "variants-TOTAL_FORMS": str(len(variants)),
        "variants-INITIAL_FORMS": str(len(variants)),
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
    }
    for i, variant in enumerate(variants):
        form.update(
            {
                f"variants-{i}-id": str(variant.id),
                f"variants-{i}-variant_name": variant.variant_name,
                f"variants-{i}-price": str(variant.price),
                f"variants-{i}-stock": str(variant.stock),
                f"variants-{i}-stock_shown": str(variant.stock),
                f"variants-{i}-pack_size": "1",
                f"variants-{i}-live": "on",
                f"variants-{i}-ORDER": str(i + 1),
            }
        )
    form.update(data)
    return {key: value for key, value in form.items() if value != ""}


def last_entry(obj):
    return entries(obj)[-1]


@pytest.fixture
def mug(product):
    small = baker.make("shop.ProductVariant", product=product, variant_name="Small", price=10, stock=5)
    large = baker.make("shop.ProductVariant", product=product, variant_name="Large", price=12, stock=3)
    return product, small, large


def edit_product(client, product, variants, **data):
    url = reverse("wagtailsnippets_shop_product:edit", args=(product.id,))
    resp = client.post(url, product_form_data(product, variants, **data))
    assert resp.status_code == 302, resp.context["form"].errors if resp.context else resp
    return last_entry(product)


def test_product_edited(client, admin, mug):
    product, small, large = mug
    other = baker.make("shop.Category", title="Gifts", slug="gifts")
    entry = edit_product(
        client,
        product,
        [small, large],
        price="15.00",
        category=str(other.id),
        **{"variants-0-stock": "8", "variants-1-live": "", "variants-1-variant_name": "Big"},
    )
    assert (entry.action, entry.user) == (activity.EDITED, admin)
    assert entry.data["changes"] == [
        "Category: Test Category → Gifts",
        "Price: £12.00 → £15.00",
        "Variant Small: Stock: +3",
        "Variant Large: Variant name: Large → Big",
        "Variant Large: Live: yes → no",
    ]
    assert entry.message.startswith("Edited: Category: Test Category → Gifts; Price:")


def test_product_variants_added_and_removed(client, admin, mug):
    product, small, large = mug
    entry = edit_product(
        client,
        product,
        [small, large],
        **{
            "variants-TOTAL_FORMS": "3",
            "variants-1-DELETE": "on",
            "variants-2-variant_name": "Medium",
            "variants-2-colour": "Blue",
            "variants-2-price": "11",
            "variants-2-stock": "2",
            "variants-2-pack_size": "1",
            "variants-2-live": "on",
            "variants-2-ORDER": "3",
        },
    )
    assert entry.data["changes"] == ["Removed variant: Large", "Added variant: Medium, Blue"]


def test_product_saved_without_changes(client, admin, mug):
    # nothing logged
    product, small, large = mug
    url = reverse("wagtailsnippets_shop_product:edit", args=(product.id,))
    assert client.post(url, product_form_data(product, [small, large])).status_code == 302
    assert entries(product, activity.EDITED) == []


def test_product_description_changed(client, admin, mug):
    product, small, large = mug
    description = json.dumps(
        {"blocks": [{"key": "a", "type": "unstyled", "text": "Lovely mug", "depth": 0,
                     "inlineStyleRanges": [], "entityRanges": []}], "entityMap": {}}
    )
    entry = edit_product(client, product, [small, large], description=description)
    assert entry.data["changes"] == ["Description changed"]


def test_category_and_discount_code_edited(client, admin, category):
    url = reverse("wagtailsnippets_shop_category:edit", args=(category.id,))
    client.post(url, {"title": "Mugs", "slug": category.slug, "description": json.dumps({"blocks": [], "entityMap": {}})})
    assert last_entry(category).data["changes"] == ["Title: Test Category → Mugs"]
    code = baker.make("shop.DiscountCode", code="PINS5", amount=Decimal("5.00"), active=True, description="")
    url = reverse("wagtailsnippets_shop_discountcode:edit", args=(code.id,))
    resp = client.post(url, {"code": "PINS5", "amount": "7.50", "description": "", "discount_type": code.discount_type})
    assert resp.status_code == 302, resp.context["form"].errors
    assert last_entry(code).data["changes"] == ["Amount: £5.00 → £7.50", "Active: yes → no"]


def test_shop_settings_edited(client, admin):
    from ..models import ShopSettings

    # (the settings' own address: the one without its id redirects to it)
    settings = ShopSettings.load()
    url = reverse("wagtailsettings:edit", args=("shop", "shopsettings", settings.pk))
    data = {"notify_email_addresses": "shop@pins.test", "reply_to": "", "shipping_cost": "5.50"}
    assert client.post(url, data).status_code == 302
    # one entry (Wagtail's, with what changed)
    (entry,) = entries(settings)
    assert (entry.action, entry.user) == (activity.SETTINGS_EDITED, admin)
    assert entry.message == (
        "Edited: Email new orders to: (blank) → shop@pins.test; Shipping cost: £4.99 → £5.50"
    )
    # saving without changes: Wagtail's own entry
    client.post(url, data)
    assert [entry.message for entry in entries(settings)][-1] == "Edited"


def test_shop_settings_saved_outside_admin(admin):
    # (not logged, as there's no Wagtail entry to add the changes to)
    from ..models import ShopSettings

    settings = ShopSettings.load()
    settings.shipping_cost = Decimal("6.00")
    settings.save()
    assert entries(settings) == []


def test_display_values():
    from django import forms

    assert activity.display_value(forms.CharField(), "") == "(blank)"
    assert activity.display_value(forms.BooleanField(), False) == "no"
    assert activity.display_value(forms.ChoiceField(choices=[("a", "Apple")]), "a") == "Apple"
    assert activity.display_value(forms.CharField(), "x" * 100).endswith("…")


def test_display_multiple_choices(category):
    from django import forms

    from ..models import Category

    other = Category.objects.create(title="Cards")
    field = forms.ModelMultipleChoiceField(queryset=Category.objects.all())
    assert activity.display_value(field, [category.pk, other]) == "Test Category, Cards"
    assert activity.display_value(field, category.pk) == "Test Category"


def test_untouched_extra_form_ignored():
    # (e.g. an extra variant form that was added but left blank)
    from types import SimpleNamespace

    from ..models import ProductVariant

    blank = SimpleNamespace(has_changed=lambda: False, instance=ProductVariant())
    formset = SimpleNamespace(model=ProductVariant, forms=[blank], can_delete=True)
    form = SimpleNamespace(changed_data=[], fields={}, cleaned_data={}, formsets={"variants": formset})
    assert activity.form_changes(form) == []


def test_sale_discounts_named(category, product):
    from ..models import Sale, SaleCategory, SaleProduct

    sale = baker.make(Sale, name="Summer")
    assert str(SaleCategory(sale=sale, category=category, discount=20)) == "Test Category (20% off)"
    assert str(SaleProduct(sale=sale, product=product, discount=5)) == "Test Product (5% off)"
    assert str(SaleProduct(sale=sale, discount=5)) == "5% off"


def test_description_saved_in_editor_unchanged(client, admin, mug):
    # a description saved outside the admin (e.g. imported) has no block keys;
    # saving it in the admin adds them, which isn't a change
    product, small, large = mug
    product.description = "<p>Lovely mug</p>"
    product.save()
    description = json.dumps(
        {"blocks": [{"key": "abcde", "type": "unstyled", "text": "Lovely mug", "depth": 0,
                     "inlineStyleRanges": [], "entityRanges": []}], "entityMap": {}}
    )
    url = reverse("wagtailsnippets_shop_product:edit", args=(product.id,))
    client.post(url, product_form_data(product, [small, large], description=description, price="13"))
    assert last_entry(product).data["changes"] == ["Price: £12.00 → £13.00"]
    product.refresh_from_db()
    assert 'data-block-key="abcde"' in product.description


def test_comparable_html():
    assert activity.comparable_html('<p data-block-key="x1">Hi</p>\n<p>There</p>') == "<p>Hi</p><p>There</p>"
    assert activity.comparable_html(None) == ""
