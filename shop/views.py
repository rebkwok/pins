from urllib.parse import parse_qsl, urlparse
import logging

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
from salesman.basket.views import BasketViewSet
from salesman.checkout.payment import payment_methods_pool
from salesman.checkout.views import CheckoutViewSet
from salesman.core.utils import get_salesman_model

from .forms import CheckoutForm
from .models import ProductVariant, Product, SHIPPING_METHODS
from .payment import PAYMENT_METHOD_DESCRIPTIONS, PayByStripe


logger = logging.getLogger(__name__)

Basket = get_salesman_model("Basket")
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


def get_basket(request):
    request.method = "GET"
    resp = BasketViewSet.as_view({"get": "list"})(request)
    data = resp.data
    data["timeout"] = Basket.objects.get(id=data["id"]).timeout
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
    if product is not None and product.live_variants.filter(stock__gt=0).exists():
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


def get_basket_quantity(request):
    request.method = "GET"
    resp = BasketViewSet.as_view({"get": "quantity"})(request)
    return resp.data["quantity"]


def get_basket_total(request):
    return get_basket(request)["total"]


def get_basket_quantity_and_total(request):
    return get_basket_quantity(request), get_basket(request)["total"]


def get_basket_item(basket, product_id):
    if not basket["items"]:
        return {}
    return next(
        (
            item
            for item in basket["items"]
            if int(item["product_id"]) == int(product_id)
        ),
        {},
    )


def get_basket_context(basket):
    basket_quantity = _get_basket_quantity(basket)
    items_by_product = {}
    for item in basket.get("items", []):
        product_type = ProductVariant.objects.get(id=item["product_id"]).product
        item["product_type"] = product_type.name
        item["category"] = product_type.category_page.title
        items_by_product.setdefault(product_type.identifier, []).append(item)
    basket["items"] = items_by_product
    return {"basket": basket, "basket_quantity": basket_quantity}


def _get_basket_quantity(basket):
    return sum(int(item["quantity"]) for item in basket.get("items", []))


def _can_increase_quantity(request, variant, value, in_basket=False):
    # value is the amount we want to change TO (may actually be a decrease if we're in the basket)
    if in_basket:
        # increasing a value from the basket; current basket quantity
        # is already incorporated into stock numbers
        # we need to check the actual basket quantity because user may have increase/decreased
        # value in the form field without actually updating
        current_quantity = get_basket_item(get_basket(request), variant.id).get(
            "quantity", 0
        )
        logger.info("Current quantity %s", current_quantity)
        logger.info("Stock %s", variant.stock)
        logger.info("New quantity %s", value)
        stock_excluding_current_basket = variant.stock + current_quantity
        return (stock_excluding_current_basket - value) >= 0
    else:
        logger.info("Variant %s", variant)
        logger.info("Stock %s", variant.stock)
        logger.info("New quantity %s", value)
        return (variant.stock - value) >= 0


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
        # Lock the variant until the item has been added, so that concurrent
        # requests can't both reserve the last items in stock
        variant = (
            ProductVariant.objects.select_for_update()
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
            resp = BasketViewSet.as_view({"post": "create"})(request)

    if can_increase:
        new_basket_quantity = get_basket_quantity(request)
        # refresh variant to ensure stock is up to date
        variant.refresh_from_db()
        resp_str = f"<div>{_basket_icon_html(request, new_basket_quantity)}</div>"
        if resp.status_code == 201:
            resp_str += f"""
                <div id='added_{product_id}' class='alert-success mt-2' hx-swap-oob='true'>Added!</div>
            """
            # update variant dropdown, including out of stock message
            variant_html = render_to_string(
                "shop/includes/select_variant_field.html",
                {"product": variant.product, "product_id": product_id},
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
            logger.error(
                "Error adding to basket: status_code %s resp %s",
                resp.status_code,
                resp.data,
            )
            resp_str += f"""
                <div id='added_{product_id}' class='alert-danger mt-2' hx-swap-oob='true'>Something went wrong</div>
                """
    else:
        logger.error(
            "Error adding to basket: can't increase quantity %r", get_basket(request)
        )
        basket_quantity = get_basket_quantity(request)
        resp_str = f"<div>{_basket_icon_html(request, basket_quantity)}</div>"
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
    request.method = "GET"
    current_item_resp = BasketViewSet.as_view({"get": "retrieve"})(request, ref=ref)
    if current_item_resp.status_code != 200:
        # no item with this ref in the basket
        raise Http404
    current_quantity = current_item_resp.data["quantity"]

    if current_quantity == new_quantity:
        # nothing to do
        result_html = f"<div id='updated_{product_id}' class='alert-info' hx-swap-oob='true'></div>"
    else:
        with transaction.atomic():
            # Lock the variant until the item has been updated, so that concurrent
            # requests can't both reserve the last items in stock.
            # Use the basket item's product, not the posted product_id.
            variant = ProductVariant.objects.select_for_update().get(
                id=current_item_resp.data["product_id"]
            )
            # Decreasing is always allowed; stock already excludes the current
            # basket quantity
            can_update = (
                new_quantity < current_quantity
                or variant.stock + current_quantity - new_quantity >= 0
            )
            if can_update:
                request.method = "PUT"
                resp = BasketViewSet.as_view({"put": "update"})(request, ref=ref)

        if not can_update:
            result_html = (
                f"<div id='updated_{product_id}' class='alert-danger' hx-swap-oob='true'>"
                "Quantity requested is not available</div>"
            )
        elif resp.status_code != 200:
            result_html = f"<div id='updated_{product_id}' class='alert-danger' hx-swap-oob='true'>Error</div>"
        else:
            basket = get_basket(request)
            basket_extra_html = render_to_string(
                "shop/includes/basket_extra.html",
                {"extra_rows": basket["extra_rows"]},
                request,
            )
            basket_item = get_basket_item(basket, product_id)
            subtotal = basket_item.get("subtotal", 0)
            total = basket_item.get("total", 0)
            result_html = f"""
                <span id='subtotal_{product_id}' hx-swap-oob='true'>{subtotal}</span>
                <span id='total_{product_id}' hx-swap-oob='true'>{total}</span>
                <span id='quantity_{product_id}' hx-swap-oob='true'>{resp.data['quantity']}</span>
                <span id='total' hx-swap-oob='true'>{basket['total']}</span>
                <div id='updated_{product_id}' class='alert-success' hx-swap-oob='true'>Basket updated</div>
                <div id='basket-extra' class='col-md-12' hx-swap-oob='true'>{basket_extra_html}</div>
            """
    return HttpResponse(result_html)


@require_POST
def delete_basket_item(request, ref):
    # This is the product variant ID
    product_id = _get_int(request.POST, "product_id")
    if _payment_in_progress(request):
        return _payment_in_progress_item_response(product_id)

    request.method = "DELETE"
    # The serialised basket identifies products (NOT variants) with their idenitifier, not id
    # Find the relevant product idenitifier
    product_identifier = get_object_or_404(ProductVariant, id=product_id).product.identifier
    # Delete the item
    resp = BasketViewSet.as_view({"delete": "destroy"})(request, ref=ref)

    if resp.status_code != 204:
        resp_str = f"""
            <div id='updated_{product_id}' class='alert-danger' hx-swap-oob='true'>Error</div>
        """
    else:
        # The item deletion was successful
        # Get the new basket quantity and the new basket
        request.method = "GET"
        new_basket_quantity = get_basket_quantity(request)
        basket = get_basket(request)
        # Does the basket still have any items (variants) for this product?
        any_product_items = any(
            1
            for item in basket["items"]
            if ProductVariant.objects.get(id=item["product_id"]).product.identifier
            == product_identifier
        )

        if not any_product_items:
            # No items for this product, hide the entire product row
            resp_str = f"<div id='row-{product_identifier}' hx-swap-oob='true'></div>"
        else:
            # Some items for this product, just hide the single variant row
            resp_str = f"<div id='row-{product_id}' hx-swap-oob='true'></div>"

        if new_basket_quantity == 0:
            # No items in the basket
            resp_str += "<div id='basket-total-and-payment' hx-swap-oob='true'><p>Basket is empty.</p></div>"
        else:
            # Still items left, update the total
            resp_str += f"<span id='total' hx-swap-oob='true'>{basket['total']}</span>"

        basket_extra_html = render_to_string(
            "shop/includes/basket_extra.html",
            {"extra_rows": basket["extra_rows"]},
            request,
        )
        resp_str += f"<div id='basket-extra' class='col-md-12' hx-swap-oob='true'>{basket_extra_html}</div>"
    return HttpResponse(resp_str)


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

    basket = get_basket(request)
    basket_context = get_basket_context(basket)
    checkout_methods = CheckoutViewSet.as_view({"get": "list"})(request)
    payment_methods = checkout_methods.data["payment_methods"]
    shipping_methods = [("collect", "Collect in store"), ("deliver", "Delivery")]
    for method in payment_methods:
        method["help"] = PAYMENT_METHOD_DESCRIPTIONS[method["identifier"]]
    return TemplateResponse(
        request,
        "shop/basket.html",
        {
            **basket_context,
            "payment_methods": payment_methods,
            "shipping_methods": shipping_methods,
            "hide_basket": True,
        },
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


@require_http_methods(["GET", "POST"])
def checkout_view(request):
    if _payment_in_progress(request):
        return HttpResponseRedirect(reverse("shop:basket"))
    payment_method = request.GET.get("payment-method")
    shipping_method = request.GET.get("shipping-method")
    valid_payment_methods = {
        method.identifier
        for method in payment_methods_pool.get_payments("basket", request)
    }
    if (
        payment_method not in valid_payment_methods
        or shipping_method not in SHIPPING_METHODS
    ):
        messages.error(request, "Please select a shipping and payment method.")
        return HttpResponseRedirect(reverse("shop:basket"))
    context = {"payment_method": payment_method, "shipping_method": shipping_method}

    if request.method == "POST":
        form = CheckoutForm(
            payment_method=payment_method,
            shipping_method=shipping_method,
            data=request.POST,
        )
        if form.is_valid():
            checkout = CheckoutViewSet.as_view({"post": "create"})(request)

            if checkout.status_code == 201:
                if payment_method == "stripe":
                    return HttpResponseRedirect(checkout.data["url"])

                parsed_url = urlparse(checkout.data["url"])
                token = dict(parse_qsl(parsed_url.query))["token"]
                return HttpResponseRedirect(
                    reverse("shop:new_order_status", args=(token,))
                )
            context["checkout_error"] = True
    else:
        # update basket with shipping method
        basket = Basket.objects.get(id=get_basket(request)["id"])
        basket.shipping_method = shipping_method
        basket.save()
        form = CheckoutForm(
            payment_method=payment_method, shipping_method=shipping_method
        )

    request.method = "GET"
    basket = get_basket(request)
    context = {**context, "form": form, **get_basket_context(basket)}

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
    order_as_basket = get_basket_context(order.serializable_data())["basket"]
    context = {
        "order": order,
        "items_by_product": order_as_basket["items"],
        "new_order": new,
        "hide_basket": True,
    }
    return TemplateResponse(request, "shop/order_status.html", context)


@require_GET
def basket_timeout(request, basket_id):
    # Only the visitor's own basket
    basket = get_existing_basket(request)
    if basket is None or basket.id != basket_id:
        raise Http404
    if basket.items.exists():
        if basket.timeout is None:
            # Shouldn't happen, as the timeout is set whenever items are added,
            # but make sure the items will be released eventually
            basket.reset_timeout()
        time_left = basket.timeout - timezone.now()
        if time_left.total_seconds() >= 0:
            return HttpResponse(f"{time_left.seconds // 60}m {time_left.seconds % 60}s")
        # expired; timeout and redirect
        Basket.clear_expired()
        messages.error(request, "Basket has expired")
        redirect_url = reverse("shop:basket")
        resp = HttpResponseRedirect(redirect_url)
        resp.headers["HX-Redirect"] = redirect_url
        return resp
    return HttpResponse(
        "<div></div><div id='basket-countdown-container' hx-swap-oob='true'></div>"
    )
