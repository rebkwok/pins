from datetime import datetime
from urllib.parse import parse_qsl, urlparse, urlunparse

import requests
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.generic import DetailView
from salesman.basket.views import BasketViewSet
from salesman.checkout.views import CheckoutViewSet

from .forms import CheckoutForm
from .models import ProductCategory, ProductVariant
from .payment import PAYMENT_METHOD_DESCRIPTIONS


def get_basket(request):
    request.method = "GET"
    resp = BasketViewSet.as_view({"get": "list"})(request)
    return resp.data


def get_basket_quantity(request):
    request.method = "GET"
    resp = BasketViewSet.as_view({"get": "quantity"})(request)
    return resp.data["quantity"]


def get_basket_total(request):
    return get_basket(request)["total"]


def get_basket_quantity_and_total(request):
    return get_basket_quantity(request), get_basket(request)["total"]


class ProductCategoryDetailView(DetailView):
    model = ProductCategory
    template_name = "shop/shop_category_page.html"
    context_object_name = "category"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data["basket_quantity"] = get_basket_quantity(self.request)
        return context_data


def decrease_quantity(request, product_id):
    value = int(request.GET.get("quantity", 1))
    if value > 1:
        value -= 1
    return _change_quantity(request, product_id, value)


def increase_quantity(request, product_id):
    value = int(request.GET.get("quantity", 1))
    value += 1
    return _change_quantity(request, product_id, value)


def _change_quantity(request, product_id, new_value):
    context = {"product_id": product_id, "value": new_value}
    resp_str = render_to_string("shop/includes/quantity_field.html", context, request)
    resp_str += f"""
        <div id='added_{product_id}' hx-swap-oob='true'></div>
        <div id='updated_{product_id}' hx-swap-oob='true'></div>
    """
    return HttpResponse(resp_str)


def add_to_basket(request, product_id):
    resp = BasketViewSet.as_view({"post": "create"})(request)
    if resp.status_code == 201:
        request.method = "GET"
        new_basket_quantity = get_basket_quantity(request)
        resp_str = f"""
            <div>{_basket_icon_html(request, new_basket_quantity)}</div>
            <div id='added_{product_id}' class='alert-success mt-2' hx-swap-oob='true'>Added!</div>
        """
    else:
        resp_str = f"""
            <div id='added_{product_id}' class='alert-danger mt-2' hx-swap-oob='true'>Something went wrong</div>
            """
    return HttpResponse(resp_str)


def update_quantity(request, ref):
    product_id = request.POST.get("product_id")
    request.method = "GET"
    current_item_resp = BasketViewSet.as_view({"get": "retrieve"})(request, ref=ref)

    if current_item_resp.data["quantity"] == int(request.POST.get("quantity")):
        # nothing to do
        result_html = (
            f"<div id='updated_{product_id}' class='alert-info' hx-swap-oob='true'>"
            "Nothing to update</div>"
        )
    else:
        request.method = "PUT"
        resp = BasketViewSet.as_view({"put": "update"})(request, ref=ref)

        if resp.status_code != 200:
            result_html = f"<div id='updated_{product_id}' class='alert-danger' hx-swap-oob='true'>Error</div>"
        else:
            new_basket_total = get_basket_total(request)
            result_html = f"""
                <span id='quantity_{product_id}' hx-swap-oob='true'>{resp.data['quantity']}</span>
                <span id='total' hx-swap-oob='true'>{new_basket_total}</span>
                <div id='updated_{product_id}' class='alert-success' hx-swap-oob='true'>Basket updated</div>
            """
    return HttpResponse(result_html)


def delete_basket_item(request, ref):
    product_id = request.POST.get("product_id")
    request.method = "DELETE"
    product_identifier = ProductVariant.objects.get(id=product_id).product.identifier
    resp = BasketViewSet.as_view({"delete": "destroy"})(request, ref=ref)

    if resp.status_code != 204:
        resp_str = f"""
            <div id='updated_{product_id}' class='alert-danger' hx-swap-oob='true'>Error</div>
        """
    else:
        request.method = "GET"
        new_basket_quantity = get_basket_quantity(request)
        basket = get_basket(request)
        any_products = any(
            1
            for item in basket["items"]
            if ProductVariant.objects.get(id=item["product_id"]).product.identifier
            == product_identifier
        )

        if not any_products:
            resp_str = f"<div id='row-{product_identifier}' hx-swap-oob='true'></div>"
        else:
            resp_str = f"<div id='row-{product_id}' hx-swap-oob='true'></div>"

        if new_basket_quantity == 0:
            resp_str += "<div id='basket-total-and-payment' hx-swap-oob='true'><p>Basket is empty.</p></div>"
        else:
            resp_str += f"<span id='total' hx-swap-oob='true'>{basket['total']}</span>"

    return HttpResponse(resp_str)


def _basket_icon_html(request, quantity):
    return render_to_string(
        "shop/includes/basket_icon.html", {"basket_quantity": quantity}, request
    )


def basket_view(request):
    resp = BasketViewSet.as_view({"get": "list"})(request)
    basket_context = get_basket_context(resp.data)
    checkout_methods = CheckoutViewSet.as_view({"get": "list"})(request)
    payment_methods = checkout_methods.data["payment_methods"]
    for method in payment_methods:
        method["help"] = PAYMENT_METHOD_DESCRIPTIONS[method["identifier"]]
    return render(
        request,
        "shop/basket.html",
        {**basket_context, "payment_methods": payment_methods, "hide_basket": True},
    )


def get_basket_context(basket):
    basket_quantity = _get_basket_quantity(basket)
    items_by_product = {}
    for item in basket.get("items", []):
        product_type = ProductVariant.objects.get(id=item["product_id"]).product
        item["product_type"] = product_type.name
        item["category"] = product_type.category
        items_by_product.setdefault(product_type.identifier, []).append(item)
    basket["items"] = items_by_product
    return {"basket": basket, "basket_quantity": basket_quantity}


def _get_basket_quantity(basket):
    return sum(int(item["quantity"]) for item in basket.get("items", []))


def checkout_view(request):
    payment_method = request.GET["payment-method"]
    context = {"payment_method": payment_method}

    if request.method == "POST":
        form = CheckoutForm(payment_method=payment_method, data=request.POST)
        if form.is_valid():
            checkout = CheckoutViewSet.as_view({"post": "create"})(request)
            if checkout.status_code == 201:
                parsed_url = urlparse(checkout.data["url"])
                token = dict(parse_qsl(parsed_url.query))["token"]
                return HttpResponseRedirect(
                    reverse("shop:new_order_status", args=(token,))
                )
            context["checkout_error"] = True
    else:
        form = CheckoutForm(payment_method=payment_method)

    request.method = "GET"
    resp = BasketViewSet.as_view({"get": "list"})(request)
    context = {**context, "form": form, **get_basket_context(resp.data)}

    return render(request, "shop/checkout.html", context)


def copy_shipping_address(request):
    billing_address_html = (
        '<label for="id_billing_address" class=" requiredField">Billing address<span class="asteriskField">*</span> </label>'
        '<textarea name="billing_address" cols="40" rows="6" class="textarea form-control" required="" id="id_billing_address">'
        f'{request.GET["shipping_address"]}'
        "</textarea>"
    )
    return HttpResponse(billing_address_html)


def new_order_view(request, token):
    return _order_status(request, token, new=True)


def order_status_view(request, token):
    return _order_status(request, token)


def _order_status(request, token, new=False):
    parsed = urlparse(request.build_absolute_uri())
    url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/api/orders/last/",
            "",
            f"token={token}&format=json",
            "",
        )
    )
    resp = requests.get(url)
    order = resp.json()
    order["date_created"] = datetime.strptime(
        order["date_created"], "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    order = get_basket_context(order)["basket"]
    context = {"order": order, "new_order": new, "hide_basket": True}
    return render(request, "shop/order_status.html", context)
