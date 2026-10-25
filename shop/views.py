import logging
import math

from django.contrib import messages
from django.core.exceptions import BadRequest
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.template.response import TemplateResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.generic import DetailView
import stripe
from salesman.checkout.payment import PaymentError, payment_methods_pool
from salesman.checkout.serializers import CheckoutSerializer
from salesman.conf import app_settings as salesman_settings
from salesman.core.utils import get_salesman_model

from .forms import CheckoutForm
from .basket_serializers import BasketSerializer
from .models import (
    DISCOUNT_CODE_IN_USE,
    DISCOUNT_CODE_INVALID,
    DISCOUNT_CODE_USED,
    SHIPPING_COLLECT,
    SHIPPING_DELIVER,
    SHIPPING_METHOD_CHOICES,
    SHIPPING_METHOD_NOTES,
    SHIPPING_METHODS,
    SHIPPING_NONE,
    DiscountCode,
    Product,
    ProductVariant,
)
from .payment import PAYMENT_METHOD_DESCRIPTIONS, PayByStripe


logger = logging.getLogger(__name__)

Basket = get_salesman_model("Basket")
BasketItem = get_salesman_model("BasketItem")
Order = get_salesman_model("Order")


# HELPER FUNCTIONS


def _get_int(data, key, default=None, min_value=None):
    """
    Get an integer from request data (GET or POST). Raises BadRequest (400) if
    it's missing (with no default), not an integer, or less than min_value.
    """
    value = data.get(key, default)
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"Invalid {key}")
    if min_value is not None and value < min_value:
        raise BadRequest(f"Invalid {key}")
    return value


def get_or_create_basket(request):
    """The request's basket, created if it doesn't exist yet"""
    basket, _ = Basket.objects.get_or_create_from_request(request)
    return basket


def serialize_basket(request, basket):
    """
    Serialized basket data (a dict, with items as a list of dicts) for templates
    and htmx responses. Serializing updates the basket instance (calculating
    totals and extra rows, and resetting its timeout).
    """
    serializer = BasketSerializer(
        basket, context={"request": request, "basket": basket}
    )
    data = dict(serializer.data)
    # serializer.data updates the basket instance in place (see docstring), so this
    # is the timeout after it's been reset; it must come after serializer.data
    data["timeout"] = basket.timeout
    return data


def get_existing_basket(request):
    return Basket.get_existing(request)


ITEM_UNAVAILABLE_MESSAGE = "Sorry, that item is no longer available."


def _is_available(variant):
    """Can this variant be added to the basket from the shop page?"""
    return variant is not None and variant.live and variant.product.live


def _item_unavailable_html(request, product_id):
    """
    Out-of-band htmx updates for a product card on the shop page when the selected
    variant is no longer available (e.g. it was made not live after the page was
    loaded): show a message below the product, and update the variant options,
    hiding the quantity and add to basket controls if none are available.
    """
    html = (
        f"<div id='added_{product_id}' class='alert-danger mt-2' hx-swap-oob='true'>"
        f"{ITEM_UNAVAILABLE_MESSAGE}</div>"
    )
    product = Product.objects.filter(id=product_id, live=True).first()
    if product is not None and not product.out_of_stock():
        variant_html = render_to_string(
            "shop/includes/select_variant_field.html", {"product": product}, request
        )
        html += (
            f"<div id='id_select_variant_wrapper_{product_id}' hx-swap-oob='true'>"
            f"{variant_html}</div>"
        )
    else:
        html += (
            f"<div id='id_select_variant_wrapper_{product_id}' hx-swap-oob='true'></div>"
            f"<div id='change_quantity_wrapper_{product_id}' hx-swap-oob='true'></div>"
        )
    return html


def _quantity_unavailable_response(request, product_id):
    """Response to the shop page +/- buttons when the item is no longer available"""
    quantity_html = render_to_string(
        "shop/includes/quantity_field.html",
        {"product_id": product_id, "value": 1},
        request,
    )
    return HttpResponse(quantity_html + _item_unavailable_html(request, product_id))


def _payment_in_progress(request):
    basket = get_existing_basket(request)
    return basket is not None and basket.payment_in_progress


PAYMENT_IN_PROGRESS_MESSAGE = (
    "Your basket can't be changed while a payment is in progress."
)


def get_existing_basket_quantity(request):
    basket = get_existing_basket(request)
    return basket.quantity if basket is not None else 0


def get_basket_item_data(basket_data, ref):
    """
    The serialized item with this ref from serialized basket data, or {}
    """
    return next(
        (item_data for item_data in basket_data["items"] if item_data["ref"] == ref),
        {},
    )


def get_basket_context(basket_data):
    """
    Template context for serialized basket data (or serialized order data).
    Groups the items by product (keyed by product identifier), adding the product
    name, category, variant name and a thumbnail image to each item. Note this modifies basket_data.
    """
    basket_quantity = sum(
        int(item_data["quantity"]) for item_data in basket_data.get("items", [])
    )
    items_by_product = {}
    for item_data in basket_data.get("items", []):
        variant = ProductVariant.objects.get(id=item_data["product_id"])
        product = variant.product
        item_data["product_type"] = product.name
        item_data["category"] = product.category.title
        item_data["variant_name"] = variant.variant_full_name()
        # a thumbnail: the variant's image, or the product's first
        item_data["image"] = variant.image or next(
            (carousel_image.image for carousel_image in product.images), None
        )
        items_by_product.setdefault(product.identifier, []).append(item_data)
    basket_data["items"] = items_by_product
    return {"basket": basket_data, "basket_quantity": basket_quantity}


def _can_increase_quantity(request, variant, value, in_basket=False):
    # value is the amount we want to change TO (may actually be a decrease if we're in the basket)
    if in_basket:
        # increasing a value from the basket; current basket quantity
        # is already incorporated into stock numbers
        # we need to check the actual basket quantity because user may have increase/decreased
        # value in the form field without actually updating
        basket = get_existing_basket(request)
        item = (
            basket.find(BasketItem.get_product_ref(variant))
            if basket is not None
            else None
        )
        current_quantity = item.quantity if item is not None else 0
        logger.debug(
            "%s: %s in basket, %s available, new quantity %s",
            variant, current_quantity, variant.available, value,
        )
        return variant.has_stock_for(value, in_basket=current_quantity)
    else:
        logger.debug("%s: %s available, new quantity %s", variant, variant.available, value)
        return variant.has_stock_for(value)


# VIEWS


class ProductDetailView(DetailView):
    queryset = Product.objects.filter(live=True)
    template_name = "shop/shop_product_page.html"
    context_object_name = "product"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data["detail_page"] = True
        return context_data


@require_GET
def decrease_quantity(request, product_id):
    # product_id in the URL is the PRODUCT
    # product_id in GET is the variant
    variant_id = _get_int(request.GET, "product_id")
    value = _get_int(request.GET, "quantity", default=1, min_value=1)
    in_basket = request.GET.get("ref") == "basket"
    # Items that are already in the basket can still be changed if they're no
    # longer live, but they can't be added from the shop page
    if not in_basket and not _is_available(
        ProductVariant.objects.filter(id=variant_id).first()
    ):
        return _quantity_unavailable_response(request, product_id)
    if value > 1:
        value -= 1
    return _change_quantity(request, product_id, value)


@require_GET
def increase_quantity(request, product_id):
    # product_id in the URL is the PRODUCT
    # product_id in GET is the variant
    # We need to increase the variant; the +/- buttons on the shop page refer to product
    variant_id = _get_int(request.GET, "product_id")
    variant = ProductVariant.objects.filter(id=variant_id).first()
    # value represents the CURRENT value of the quantity field (pre-increase)
    value = _get_int(request.GET, "quantity", default=1, min_value=1)
    in_basket = request.GET.get("ref") == "basket"
    # Items that are already in the basket can still be changed if they're no
    # longer live, but they can't be added from the shop page
    if not in_basket and not _is_available(variant):
        return _quantity_unavailable_response(request, product_id)
    if variant is None:
        raise Http404
    # We click on this button to increase the quantity from its current value
    # check that we can increase to this value plus 1
    can_increase = _can_increase_quantity(request, variant, value + 1, in_basket)
    if can_increase:
        value += 1
    return _change_quantity(request, product_id, value, can_increase=can_increase)


def _change_quantity(request, product_id, new_value, can_increase=True):
    context = {"product_id": product_id, "value": new_value}
    resp_str = render_to_string("shop/includes/quantity_field.html", context, request)
    resp_str += f"""
        <div id='added_{product_id}' hx-swap-oob='true'></div>
        <div id='updated_{product_id}' hx-swap-oob='true'></div>
    """
    if not can_increase:
        resp_str += (
            f"<div id='updated_{product_id}' class='alert-info' hx-swap-oob='true'>"
            "Can't increase quantity</div>"
        )
        resp = HttpResponse(resp_str)
        return resp
    resp = HttpResponse(resp_str)
    resp.headers["HX-Trigger"] = "quantity-changed"
    return resp


@require_POST
def add_to_basket(request, product_id):
    # product_id in the URL is the PRODUCT
    # product_id in POST is the variant
    variant_id = _get_int(request.POST, "product_id")
    quantity = _get_int(request.POST, "quantity", min_value=1)
    if _payment_in_progress(request):
        resp_str = f"<div>{_basket_icon_html(request, get_existing_basket_quantity(request))}</div>"
        resp_str += (
            f"<div id='added_{product_id}' class='alert-danger mt-2' hx-swap-oob='true'>"
            f"{PAYMENT_IN_PROGRESS_MESSAGE} <a href='{reverse('shop:basket')}'>View basket</a></div>"
        )
        return HttpResponse(resp_str)

    with transaction.atomic():
        # Lock the variant and its product (whose stock it may share) until the
        # item has been added, so that concurrent requests can't both reserve
        # the last items in stock
        variant = (
            ProductVariant.objects.select_related("product")
            .select_for_update()
            .filter(id=variant_id, live=True, product__live=True)
            .first()
        )
        if variant is None:
            resp_str = f"<div>{_basket_icon_html(request, get_existing_basket_quantity(request))}</div>"
            return HttpResponse(resp_str + _item_unavailable_html(request, product_id))
        # add_to_basket is called from the shop page, not the basket page; we're
        # adding this entire quantity to the basket, but we're not incrementing
        # it, so just check we can add the current quantity
        can_increase = _can_increase_quantity(
            request, variant, quantity, in_basket=False
        )
        if can_increase:
            basket = get_or_create_basket(request)
            basket.add(variant, quantity=quantity)
            # Calculate totals and reset the basket timeout
            basket.update(request)

    if can_increase:
        # refresh the variant and product to ensure stock is up to date
        variant.refresh_from_db()
        variant.product.refresh_from_db()
        resp_str = f"<div>{_basket_icon_html(request, basket.quantity)}</div>"
        resp_str += f"""
            <div id='added_{product_id}' class='alert-success mt-2' hx-swap-oob='true'>
                Added! <a href='{reverse("shop:basket")}'>Go to basket</a>
            </div>
        """
        # update variant dropdown, including out of stock message
        variant_html = render_to_string(
            "shop/includes/select_variant_field.html",
            {"product": variant.product},
            request,
        )
        resp_str += f"<div id='id_select_variant_wrapper_{ product_id }' hx-swap-oob='true'>{variant_html}</div>"

        if variant.product.out_of_stock():
            # hide quantity change and add-to-basket button
            resp_str += f"<div id='change_quantity_wrapper_{ product_id }' hx-swap-oob='true'></div>"
        else:
            # set quantity back to 1
            quantity_to_add_html = render_to_string(
                "shop/includes/quantity_field.html",
                {"product_id": product_id, "value": 1},
                request,
            )
            resp_str += f"""
                <div id='id_quantity_wrapper_{ product_id }' hx-swap-oob='true'>{quantity_to_add_html}</div>
            """
    else:
        logger.info(
            "Can't add %s x %s to basket: %s available", quantity, variant, variant.available
        )
        resp_str = f"<div>{_basket_icon_html(request, get_existing_basket_quantity(request))}</div>"
        resp_str += f"""
        <div id='added_{product_id}' class='alert-danger mt-2' hx-swap-oob='true'>Quantity requested is not available</div>
        """

    return HttpResponse(resp_str)


@require_POST
def update_quantity(request, ref):
    # Called from basket
    # Here product ID is the variant ID
    product_id = _get_int(request.POST, "product_id")
    new_quantity = _get_int(request.POST, "quantity", min_value=1)
    if _payment_in_progress(request):
        return _payment_in_progress_item_response(product_id)
    basket, item = _find_basket_item(request, ref, product_id)
    current_quantity = item.quantity

    if current_quantity == new_quantity:
        # nothing to do
        result_html = f"<div id='updated_{product_id}' class='alert-info' hx-swap-oob='true'></div>"
    else:
        with transaction.atomic():
            # Lock the variant and its product (whose stock it may share) until
            # the item has been updated, so that concurrent requests can't both
            # reserve the last items in stock.
            variant = (
                ProductVariant.objects.select_related("product")
                .select_for_update()
                .get(id=item.product_id)
            )
            # Decreasing is always allowed; stock already excludes the current
            # basket quantity
            can_update = new_quantity < current_quantity or variant.has_stock_for(
                new_quantity, in_basket=current_quantity
            )
            if can_update:
                item.quantity = new_quantity
                item.save(update_fields=["quantity", "date_updated"])

        if not can_update:
            result_html = (
                f"<div id='updated_{product_id}' class='alert-danger' hx-swap-oob='true'>"
                "Quantity requested is not available</div>"
            )
        else:
            basket_data = serialize_basket(request, basket)
            basket_extra_html = render_to_string(
                "shop/includes/basket_extra.html",
                {"extra_rows": basket_data["extra_rows"]},
                request,
            )
            item_data = get_basket_item_data(basket_data, ref)
            subtotal = item_data.get("subtotal", 0)
            total = item_data.get("total", 0)
            result_html = f"""
                <span id='subtotal_{product_id}' hx-swap-oob='true'>{subtotal}</span>
                <span id='total_{product_id}' hx-swap-oob='true'>{total}</span>
                <span id='quantity_{product_id}' hx-swap-oob='true'>{item.quantity}</span>
                <span id='total' hx-swap-oob='true'>{basket_data['total']}</span>
                <div id='updated_{product_id}' class='alert-success' hx-swap-oob='true'>Basket updated</div>
                <div id='basket-extra' hx-swap-oob='true'>{basket_extra_html}</div>
            """ + _discount_oob_html(request, basket)
    return HttpResponse(result_html)


@require_POST
def delete_basket_item(request, ref):
    # This is the product variant ID
    product_id = _get_int(request.POST, "product_id")
    if _payment_in_progress(request):
        return _payment_in_progress_item_response(product_id)

    basket, _ = _find_basket_item(request, ref, product_id)
    # The serialised basket identifies products (NOT variants) with their identifier
    variant = ProductVariant.objects.filter(id=product_id).first()
    product_identifier = variant.product.identifier if variant else None
    basket.remove(ref)
    basket_data = serialize_basket(request, basket)

    # Does the basket still have any items (variants) for this product?
    any_product_items = any(
        other_item.product is not None
        and other_item.product.product.identifier == product_identifier
        for other_item in basket.get_items()
    )
    if product_identifier is not None and not any_product_items:
        # No items for this product, hide the entire product row
        resp_str = f"<div id='row-{product_identifier}' hx-swap-oob='true'></div>"
    else:
        # Some items for this product, just hide the single variant row
        resp_str = f"<div id='row-{product_id}' hx-swap-oob='true'></div>"

    if basket.quantity == 0:
        # No items in the basket: reload the page, which shows the empty basket
        # (without the countdown and discount code)
        resp = HttpResponse()
        resp.headers["HX-Refresh"] = "true"
        return resp
    else:
        # Still items left, update the total, and the shipping options (e.g. if
        # nothing left needs shipping)
        resp_str += f"<span id='total' hx-swap-oob='true'>{basket_data['total']}</span>"
        resp_str += render_to_string(
            "shop/includes/basket_checkout_options.html",
            {**get_checkout_options_context(request, basket), "oob": True},
            request,
        )
        resp_str += _discount_oob_html(request, basket)

    basket_extra_html = render_to_string(
        "shop/includes/basket_extra.html",
        {"extra_rows": basket_data["extra_rows"]},
        request,
    )
    resp_str += f"<div id='basket-extra' hx-swap-oob='true'>{basket_extra_html}</div>"
    return HttpResponse(resp_str)


def _find_basket_item(request, ref, product_id):
    """
    The request's basket and its item with this ref. Raises 404 if there isn't
    one, or if it isn't for the posted product (variant) id, which is used to
    identify the elements to update in the response.
    """
    basket = get_existing_basket(request)
    item = basket.find(ref) if basket is not None else None
    if item is None or item.product_id != product_id:
        raise Http404
    return basket, item


def _basket_icon_html(request, quantity):
    return render_to_string(
        "shop/includes/basket_icon.html", {"basket_quantity": quantity}, request
    )


def _payment_in_progress_item_response(product_id):
    return HttpResponse(
        f"<div id='updated_{product_id}' class='alert-danger' hx-swap-oob='true'>"
        f"{PAYMENT_IN_PROGRESS_MESSAGE}</div>"
    )


@require_GET
def basket_view(request):
    existing_basket = get_existing_basket(request)
    if existing_basket is not None and existing_basket.payment_in_progress:
        # The customer has come back to their basket during checkout; check
        # whether the payment has completed or expired
        order = PayByStripe.check_basket_payment(request, existing_basket)
        if order is not None:
            return HttpResponseRedirect(
                reverse("shop:new_order_status", args=(order.token,))
            )
        existing_basket.refresh_from_db()
        if existing_basket.payment_in_progress:
            return TemplateResponse(
                request,
                "shop/basket_payment_in_progress.html",
                {
                    "stripe_session_url": existing_basket.stripe_session_url,
                    "hide_basket": True,
                },
            )

    if (
        existing_basket is not None
        and existing_basket.shipping_method not in SHIPPING_METHODS
    ):
        # The basket page shows the basket's shipping method (delivery or
        # collection, kept e.g. when a discount code is applied or the customer
        # comes back from the checkout). "No shipping needed" (set at the
        # checkout) becomes delivery, which is selected (and the total includes
        # its cost) if something now needs shipping.
        existing_basket.shipping_method = SHIPPING_DELIVER
        existing_basket.save(update_fields=["shipping_method"])
    # Viewing the basket page doesn't create a basket
    basket_data = (
        serialize_basket(request, existing_basket)
        if existing_basket is not None
        else {"items": []}
    )
    return TemplateResponse(
        request,
        "shop/basket.html",
        {
            **get_basket_context(basket_data),
            **get_checkout_options_context(request, existing_basket),
            **get_discount_context(existing_basket),
            **get_countdown_context(existing_basket),
            "hide_basket": True,
        },
    )


def get_countdown_context(basket):
    """
    Context for the basket page's countdown (shop/includes/basket_countdown.html),
    if the basket has items (and a timeout)
    """
    if basket is None or basket.timeout is None or not basket.items.exists():
        return {"seconds_left": None}
    seconds_left = max(0, math.ceil((basket.timeout - timezone.now()).total_seconds()))
    return {
        "seconds_left": seconds_left,
        "time_left": f"{seconds_left // 60}m {seconds_left % 60}s",
        "countdown_url": reverse("shop:basket_timeout", args=(basket.id,)),
    }


def get_discount_context(basket):
    """
    Context for the basket's discount code (shop/includes/basket_discount.html).
    The basket must have been updated (e.g. serialized), which applies the code.
    """
    code = basket.extra.get(basket.DISCOUNT_CODE_KEY) if basket is not None else None
    if not code:
        return {"discount_code": None}
    return {
        "discount_code": code,
        "discount_problem": basket.discount_problem,
        "discount_covers_order": basket.total == 0,
        "discount_unused": basket.discount_unused,
    }


def _discount_problem_redirect(request, basket):
    """
    Back to the basket, saying why its discount code doesn't apply. A code that
    isn't valid (invalid, disabled, used, or being paid for in another basket) is
    removed; one that would leave too little to pay is kept, as it applies if the
    basket changes, with the reason shown on the basket.
    """
    problem = basket.discount_problem
    if problem in (DISCOUNT_CODE_INVALID, DISCOUNT_CODE_USED, DISCOUNT_CODE_IN_USE):
        code = basket.extra.get(basket.DISCOUNT_CODE_KEY)
        basket.set_discount_code(None)
        messages.error(request, f"Discount code {code} removed: {problem}")
    else:
        messages.error(request, problem)
    return HttpResponseRedirect(reverse("shop:basket"))


def _discount_oob_html(request, basket):
    """The basket's discount code section, to replace it (htmx)"""
    return render_to_string(
        "shop/includes/basket_discount.html",
        {**get_discount_context(basket), "oob": True},
        request,
    )


def _discount_code_response(request, basket, level, message):
    """
    After applying or removing a discount code: with htmx, the basket page's
    summary (totals, code and options), with the message under the code, so the
    page isn't reloaded (and keeps its scroll position); otherwise back to the
    basket page, with the message. (With htmx, an empty basket or one being paid
    for reloads the page, which shows why.)
    """
    if request.headers.get("HX-Request") != "true":
        if message:
            messages.add_message(request, level, message)
        return HttpResponseRedirect(reverse("shop:basket"))
    if basket is None or not basket.count or basket.payment_in_progress:
        if message:
            messages.add_message(request, level, message)
        resp = HttpResponse()
        resp.headers["HX-Refresh"] = "true"
        return resp
    context = {
        **get_basket_context(serialize_basket(request, basket)),
        **get_checkout_options_context(request, basket),
        **get_discount_context(basket),
        "discount_message": message,
        "discount_message_level": "success" if level == messages.SUCCESS else "error",
    }
    return HttpResponse(
        render_to_string("shop/includes/basket_summary.html", context, request)
    )


@require_POST
def apply_discount_code(request):
    """Apply a discount code to the basket (from the basket page)"""
    basket = get_existing_basket(request)
    if basket is None or not basket.count:
        return _discount_code_response(request, basket, messages.ERROR, "Your basket is empty.")
    if basket.payment_in_progress:
        return _discount_code_response(
            request, basket, messages.ERROR, PAYMENT_IN_PROGRESS_MESSAGE
        )
    code = DiscountCode.find(request.POST.get("code"))
    problem = DISCOUNT_CODE_INVALID if code is None else code.unavailable_reason(basket)
    if problem is None:
        basket.set_discount_code(code)
        basket.update(request)
        # e.g. it would leave too little to pay
        problem = basket.discount_problem
        if problem is not None:
            basket.set_discount_code(None)
    if problem is not None:
        return _discount_code_response(request, basket, messages.ERROR, problem)
    return _discount_code_response(
        request, basket, messages.SUCCESS, f"Discount code {code.code} applied."
    )


@require_POST
def remove_discount_code(request):
    """Remove the discount code from the basket (from the basket page)"""
    basket = get_existing_basket(request)
    if basket is not None and basket.payment_in_progress:
        return _discount_code_response(
            request, basket, messages.ERROR, PAYMENT_IN_PROGRESS_MESSAGE
        )
    if basket is None:
        return _discount_code_response(request, basket, messages.INFO, None)
    basket.set_discount_code(None)
    return _discount_code_response(request, basket, messages.INFO, "Discount code removed.")


def get_checkout_options_context(request, basket):
    """
    Context for the basket page's shipping and payment options
    (shop/includes/basket_checkout_options.html)
    """
    payment_methods = [
        {
            "identifier": method.identifier,
            "label": method.label,
            "help": PAYMENT_METHOD_DESCRIPTIONS[method.identifier],
        }
        for method in payment_methods_pool.get_payments("basket", request)
    ]
    # (value, label, note); none if nothing in the basket needs shipping
    requires_shipping = basket is not None and basket.requires_shipping
    shipping_methods = (
        [
            (method, label, SHIPPING_METHOD_NOTES.get(method, ""))
            for method, label in SHIPPING_METHODS.items()
        ]
        if requires_shipping
        else []
    )
    return {
        "payment_methods": payment_methods,
        "shipping_methods": shipping_methods,
        "requires_shipping": requires_shipping,
        # The basket's shipping method, which its total includes
        "selected_shipping_method": (
            basket.shipping_method if basket is not None else SHIPPING_DELIVER
        ),
    }


@require_POST
def update_shipping_method(request):
    """
    The shipping method has been changed on the basket page (htmx): save it on
    the basket, and update the total (which includes any shipping cost).
    """
    basket = get_existing_basket(request)
    shipping_method = request.POST.get("shipping-method")
    if (
        basket is None
        or basket.payment_in_progress
        or shipping_method not in SHIPPING_METHODS
    ):
        return HttpResponse("")
    basket.shipping_method = shipping_method
    basket.save(update_fields=["shipping_method"])
    basket_data = serialize_basket(request, basket)
    basket_extra_html = render_to_string(
        "shop/includes/basket_extra.html",
        {"extra_rows": basket_data["extra_rows"]},
        request,
    )
    return HttpResponse(
        f"<span id='total' hx-swap-oob='true'>{basket_data['total']}</span>"
        f"<div id='basket-extra' hx-swap-oob='true'>{basket_extra_html}</div>"
        + _discount_oob_html(request, basket)
    )


@require_POST
def cancel_payment(request):
    """Cancel the basket's in-progress payment, so the basket can be changed"""
    basket = get_existing_basket(request)
    if basket is not None and basket.payment_in_progress:
        try:
            if PayByStripe.cancel_basket_payment(basket):
                messages.info(request, "Payment cancelled.")
            # Otherwise the payment has completed; the basket view will fulfil it
        except stripe.StripeError:
            logger.exception(
                "Error cancelling Stripe session %s", basket.stripe_session_id
            )
            messages.error(
                request, "Sorry, your payment couldn't be cancelled. Please try again."
            )
    return HttpResponseRedirect(reverse("shop:basket"))


CHECKOUT_ERROR = "There was an error submitting this order"


def _checkout(request, basket):
    """
    Process the checkout with salesman's checkout serializer: save the
    customer's details on the basket and start the payment.
    Returns (the payment URL, None), or (None, an error message for the
    customer) if the checkout failed.
    """
    if not (
        salesman_settings.SALESMAN_ALLOW_ANONYMOUS_USER_CHECKOUT
        or request.user.is_authenticated
    ):
        return None, CHECKOUT_ERROR
    basket.update(request)
    serializer = CheckoutSerializer(
        data=request.POST, context={"request": request, "basket": basket}
    )
    if not serializer.is_valid():
        logger.error("Checkout failed: %s", serializer.errors)
        return None, CHECKOUT_ERROR
    try:
        serializer.save()
    except PaymentError as e:
        # Payment errors are written for the customer
        logger.error("Checkout payment failed: %s", e)
        return None, str(e)
    return serializer.data["url"], None


@require_http_methods(["GET", "POST"])
def checkout_view(request):
    if _payment_in_progress(request):
        return HttpResponseRedirect(reverse("shop:basket"))
    payment_method = request.GET.get("payment-method")
    existing_basket = get_existing_basket(request)
    if existing_basket is not None and existing_basket.requires_shipping:
        # Delivery or collection
        shipping_method = request.GET.get("shipping-method")
        valid_shipping_methods = SHIPPING_METHODS
    else:
        # Nothing needs shipping (whatever the basket page sent, in case the
        # basket has changed since)
        shipping_method = SHIPPING_NONE
        valid_shipping_methods = [SHIPPING_NONE]
    valid_payment_methods = {
        method.identifier
        for method in payment_methods_pool.get_payments("basket", request)
    }
    if (
        payment_method not in valid_payment_methods
        or shipping_method not in valid_shipping_methods
    ):
        messages.error(request, "Please select a shipping and payment method.")
        return HttpResponseRedirect(reverse("shop:basket"))
    context = {
        "payment_method": payment_method,
        "shipping_method": shipping_method,
        "shipping_method_label": SHIPPING_METHOD_CHOICES[shipping_method],
        "collect_warning": shipping_method == SHIPPING_COLLECT,
    }
    basket = get_or_create_basket(request)
    # The basket's total includes shipping for delivery
    basket.shipping_method = shipping_method
    basket.save()
    basket.update(request)
    if basket.discount_problem:
        # The discount code doesn't apply (any more): back to the basket, rather
        # than paying the full price
        return _discount_problem_redirect(request, basket)
    # A discount code may cover the whole basket, so there's nothing to pay
    free = basket.count > 0 and basket.total == 0

    if request.method == "POST":
        form = CheckoutForm(
            payment_method=payment_method,
            shipping_method=shipping_method,
            free=free,
            data=request.POST,
        )
        if form.is_valid():
            url, error = _checkout(request, basket)
            if url is not None:
                # Stripe checkout, or the new order status page
                return HttpResponseRedirect(url)
            context["checkout_error"] = error
    else:
        form = CheckoutForm(
            payment_method=payment_method, shipping_method=shipping_method, free=free
        )

    context = {
        **context,
        "form": form,
        # Paying by card: the customer goes to Stripe's page to pay
        "pay_with_stripe": payment_method == "stripe" and not free,
        **get_basket_context(serialize_basket(request, basket)),
        **get_discount_context(basket),
    }

    return TemplateResponse(request, "shop/checkout.html", context)


@require_GET
def new_order_view(request, token):
    return _order_status(request, token, new=True)


@require_GET
def order_status_view(request, token):
    return _order_status(request, token)


def _order_status(request, token, new=False):
    order = get_object_or_404(Order, token=token)
    # Group the order items by product, as for the basket
    order_data = get_basket_context(order.serializable_data())["basket"]
    context = {
        "order": order,
        "items_by_product": order_data["items"],
        "new_order": new,
        "hide_basket": True,
    }
    return TemplateResponse(request, "shop/order_status.html", context)


BASKET_EXPIRED_MESSAGE = "Your basket has expired."
BASKET_CHANGED_MESSAGE = "Your basket has changed since this page was loaded."


def _refresh_basket_page(request, message=None):
    """
    Reload the basket page (htmx), so it shows the basket as it is now, with an
    optional message
    """
    if message:
        messages.error(request, message)
    resp = HttpResponse("")
    resp.headers["HX-Refresh"] = "true"
    return resp


@require_GET
def basket_timeout(request, basket_id):
    """
    The time left before the basket's items are released, for the basket page's
    countdown (htmx, every minute, see basket_countdown.js). If the basket has
    expired or changed since the page was loaded, the page is reloaded instead.
    """
    basket = get_existing_basket(request)
    if basket is None or basket.id != basket_id:
        # e.g. the basket has been checked out or removed (perhaps in another
        # tab), or merged into the user's basket when they logged in. (Another
        # visitor's basket's time isn't shown.)
        return _refresh_basket_page(request, BASKET_CHANGED_MESSAGE)
    if not basket.items.exists():
        # Emptied since the page was loaded: expired items are cleared (and the
        # timeout unset) by clear_expired; otherwise e.g. emptied in another tab
        return _refresh_basket_page(
            request, BASKET_EXPIRED_MESSAGE if basket.timeout is None else None
        )
    if basket.timeout is None:
        # Shouldn't happen, as the timeout is set whenever items are added,
        # but make sure the items will be released eventually
        basket.reset_timeout()
    if basket.timeout >= timezone.now():
        return TemplateResponse(
            request, "shop/includes/basket_countdown.html", get_countdown_context(basket)
        )
    # Expired now
    Basket.clear_expired()
    return _refresh_basket_page(request, BASKET_EXPIRED_MESSAGE)
