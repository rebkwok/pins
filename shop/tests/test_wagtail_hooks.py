import re
from decimal import Decimal

import pytest
from django.utils.text import slugify
from wagtail.test.utils.form_data import rich_text
from model_bakery import baker

from salesman.admin.wagtail_hooks import OrderAdmin as SalesmanOrderAdmin
from django.urls import reverse
from salesman.core.utils import get_salesman_model
from salesman.orders.serializers import OrderSerializer as SalesmanOrderSerializer

from ..models import CategoryPage
from ..wagtail_hooks import OrderAdmin

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True, is_staff=True))
    yield client


def contact_panel_fields(panels):
    return [child.attr for child in panels[2].children]


def test_order_admin_adds_name_and_shipping_method():
    assert OrderAdmin.list_display == [
        "__str__",
        "email",
        "name",
        "status_display",
        "shipping_method",
        "total_display",
        "is_paid_display",
        "refunds_list_display",
        "date_created",
    ]
    assert OrderAdmin.search_fields == ["ref", "email", "token", "name"]
    assert contact_panel_fields(OrderAdmin.default_panels) == [
        "customer_display",
        "email",
        "name",
        "shipping_method",
        "shipping_address_display",
        "billing_address_display",
    ]


def test_salesman_order_admin_and_serializer_not_changed():
    # The shop's order admin doesn't change salesman's lists and panels
    assert "name" not in SalesmanOrderAdmin.list_display
    assert "shipping_method" not in SalesmanOrderAdmin.list_display
    assert "name" not in SalesmanOrderAdmin.search_fields
    assert contact_panel_fields(SalesmanOrderAdmin.default_panels) == [
        "customer_display",
        "email",
        "shipping_address_display",
        "billing_address_display",
    ]
    assert "name" not in SalesmanOrderSerializer.Meta.fields


def test_order_admin_index(admin_client, order):
    url = OrderAdmin().url_helper.index_url
    resp = admin_client.get(url, {"q": "Test User"})
    assert resp.status_code == 200
    content = resp.content.decode()
    assert order.ref in content
    assert "Collect in person" in content


def test_order_admin_edit(admin_client, order):
    url = OrderAdmin().url_helper.get_action_url("edit", order.pk)
    resp = admin_client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Test User" in content
    assert "Collect in person" in content


def panel_fields(panels, index):
    return [
        getattr(child, "attr", None) or child.field_name
        for child in panels[index].children
    ]


def test_order_admin_adds_refunds():
    # Status
    assert panel_fields(OrderAdmin.default_panels, 1) == [
        "status",
        "date_created",
        "date_updated",
        "is_paid",
        "refunds_display",
    ]
    # Totals
    assert panel_fields(OrderAdmin.default_panels, 3) == [
        "subtotal_display",
        "extra_rows_display",
        "total_display",
        "amount_paid_display",
        "refunds_display",
        "amount_outstanding_display",
    ]
    assert "refunds_display" not in panel_fields(SalesmanOrderAdmin.default_panels, 3)


def field_values(content):
    """The admin page's read-only fields, as {label: value}"""
    fields = re.findall(
        r'<h3 class="w-field__label">(.*?)</h3>\s*<div>(.*?)</div>', content, re.S
    )
    return {label.strip(): value.strip() for label, value in fields}


@pytest.mark.parametrize(
    "refunds,paid_icon,refunded,outstanding",
    [
        ([], "icon-tick", "-", "0.00"),
        (["-5.00"], "icon-tick", "5.00 (partially refunded)", "0.00"),
        (["-5.00", "-15.00"], "icon-tick", "20.00 (fully refunded)", "0.00"),
    ],
)
def test_order_admin_edit_refunds(admin_client, order, refunds, paid_icon, refunded, outstanding):
    # order total is £20
    order.pay(amount=Decimal("20.00"), transaction_id="pi_1")
    for index, amount in enumerate(refunds):
        order.pay(amount=Decimal(amount), transaction_id=f"re_{index}")
    url = OrderAdmin().url_helper.get_action_url("edit", order.pk)
    values = field_values(admin_client.get(url).content.decode())
    # refunds don't make the order unpaid or outstanding
    assert paid_icon in values["Is paid"]
    assert values["Amount paid"] == "20.00"
    assert values["Refunded"] == refunded
    assert values["Amount outstanding"] == outstanding


def test_order_admin_edit_unpaid(admin_client, order):
    url = OrderAdmin().url_helper.get_action_url("edit", order.pk)
    values = field_values(admin_client.get(url).content.decode())
    assert "icon-cross" in values["Is paid"]
    assert values["Amount paid"] == "0.00"
    assert values["Amount outstanding"] == "20.00"


@pytest.fixture
def refunded_orders(basket):
    # unpaid, paid, partially refunded and fully refunded orders (totals £20)
    orders = [Order.objects.create_from_basket(basket, request=None) for _ in range(4)]
    for order in orders[1:]:
        order.pay(amount=Decimal("20.00"), transaction_id=f"pi_{order.id}")
    orders[2].pay(amount=Decimal("-5.00"), transaction_id="re_1")
    orders[3].pay(amount=Decimal("-20.00"), transaction_id="re_2")
    yield orders


def test_order_admin_index_refunds(admin_client, refunded_orders):
    resp = admin_client.get(OrderAdmin().url_helper.index_url)
    content = resp.content.decode()
    assert re.search(r"<th[^>]*>\s*Refunds", content)
    # in the column, and in the filter
    assert content.count("Partially refunded") == 2
    assert content.count("Fully refunded") == 2


@pytest.mark.parametrize(
    "value,expected", [("partial", [2]), ("full", [3]), ("none", [0, 1]), ("", [0, 1, 2, 3])]
)
def test_order_admin_refunds_filter(admin_client, refunded_orders, value, expected):
    resp = admin_client.get(OrderAdmin().url_helper.index_url, {"refunds": value})
    shown = set(resp.context["object_list"])
    assert shown == {refunded_orders[index] for index in expected}


def breadcrumbs(content):
    """The breadcrumb labels on an admin page"""
    nav = re.search(r'<nav[^>]*aria-label="Breadcrumb">(.*?)</nav>', content, re.S).group(1)
    return [
        " ".join(re.sub(r"<[^>]+>", " ", item).split())
        for item in re.findall(r"<li.*?</li>", nav, re.S)
    ]


@pytest.mark.parametrize(
    "model,label,new_label",
    [
        ("product", "Products", "New: Product"),
        ("productvariant", "Product variants", "New: Product variant"),
        ("sale", "Sales", "New: Sale"),
    ],
)
def test_shop_stock_breadcrumbs(
    admin_client, product, sale_with_items, model, label, new_label
):
    instance = {
        "product": product,
        "productvariant": baker.make("shop.ProductVariant", product=product),
        "sale": sale_with_items,
    }[model]
    prefix = f"wagtailsnippets_shop_{model}"
    pages = [
        (reverse(f"{prefix}:list"), []),
        (reverse(f"{prefix}:add"), [new_label]),
        (reverse(f"{prefix}:edit", args=(instance.pk,)), [str(instance)]),
    ]
    for url, last in pages:
        content = admin_client.get(url).content.decode()
        assert breadcrumbs(content) == ["Home", "Shop Stock", label, *last]
        # the menu has no page, so Shop Stock isn't a link
        assert not re.search(r"<a[^>]*>\s*Shop Stock", content)


def test_product_variants_list_order(admin_client, product):
    # products in two categories (product's is "Test Category"), created out of
    # order
    cards = product.category_page.get_parent().add_child(
        instance=CategoryPage(title="Cards", slug="cards")
    )
    mug = baker.make("shop.Product", category_page=product.category_page, name="Mug")
    calendar = baker.make("shop.Product", category_page=cards, name="Calendar")
    baker.make("shop.ProductVariant", product=mug, variant_name="Large", sort_order=2)
    baker.make("shop.ProductVariant", product=product, variant_name="Small", sort_order=1)
    baker.make("shop.ProductVariant", product=calendar, variant_name="Single", sort_order=1)
    baker.make("shop.ProductVariant", product=mug, variant_name="Small", sort_order=1)
    resp = admin_client.get(reverse("wagtailsnippets_shop_productvariant:list"))
    # by category, then product, then the product's variant order
    assert [str(variant) for variant in resp.context["object_list"]] == [
        "Calendar - Single",
        "Mug - Small",
        "Mug - Large",
        "Test Product - Small",
    ]
    # no "Sort item order" for reordering all the variants together
    assert "Sort item order" not in resp.content.decode()


def test_products_list_order(admin_client, product):
    # by category, then the shop page order (index), then name; two categories
    # with the same title aren't mixed together
    shop_page = product.category_page.get_parent()
    cards = shop_page.add_child(instance=CategoryPage(title="Cards", slug="cards"))
    # a duplicate title (allowed in the database, but not in the admin form)
    cards_2 = shop_page.add_child(instance=CategoryPage(title="Cards", slug="cards-2"))
    baker.make("shop.Product", category_page=cards_2, name="Notebook", index=1)
    baker.make("shop.Product", category_page=cards, name="Card B", index=2)
    baker.make("shop.Product", category_page=cards, name="Calendar", index=5)
    baker.make("shop.Product", category_page=cards, name="Card A", index=2)
    resp = admin_client.get(reverse("wagtailsnippets_shop_product:list"))
    assert [p.name for p in resp.context["object_list"]] == [
        "Card A",
        "Card B",
        "Calendar",
        "Notebook",
        "Test Product",
    ]
    assert "Sort item order" not in resp.content.decode()


def category_form(shop_page, title, instance=None):
    form_class = CategoryPage.get_edit_handler().get_form_class()
    data = {
        "title": title,
        "slug": slugify(title) + "-new",
        "body": rich_text(""),
        "index": "1",
        "comments-TOTAL_FORMS": "0",
        "comments-INITIAL_FORMS": "0",
        "comments-MIN_NUM_FORMS": "0",
        "comments-MAX_NUM_FORMS": "1000",
    }
    return form_class(
        data=data,
        instance=instance or CategoryPage(),
        parent_page=shop_page,
        for_user=baker.make("auth.User", is_superuser=True),
    )


@pytest.mark.parametrize("title", ["Test Category", "test category"])
def test_category_title_unique(category_page, title):
    form = category_form(category_page.get_parent(), title)
    assert not form.is_valid()
    assert form.errors["title"] == [
        f"There's already a category called '{title}' in this shop."
    ]


def test_category_title_unique_new_title(category_page):
    assert category_form(category_page.get_parent(), "Clothing").is_valid()


def test_category_title_unique_editing(category_page):
    # a category can keep its own title
    form = category_form(category_page.get_parent(), "Test Category", category_page)
    assert form.is_valid(), form.errors
