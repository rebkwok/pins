"""
Products' order in their category (dragged on the category's page in the
admin), the category page's products, and the categories list's links.
"""

import html
import re

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from model_bakery import baker

from ..models import Product

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    client.force_login(baker.make("auth.User", is_superuser=True))
    yield client


@pytest.fixture
def products(category):
    return [
        Product.objects.create(category=category, name=name, price=1)
        for name in ["Mug", "Card", "Calendar"]
    ]


def names(category):
    return list(category.products.order_by("sort_order").values_list("name", flat=True))


def test_new_products_go_last(category, products):
    assert [p.sort_order for p in products] == [0, 1, 2]
    assert names(category) == ["Mug", "Card", "Calendar"]
    # in another category, they start again
    other = baker.make("shop.Category", title="Other")
    assert Product.objects.create(category=other, name="Bag", price=1).sort_order == 0


def test_moved_product_goes_last(category, products):
    other = baker.make("shop.Category", title="Other")
    Product.objects.create(category=other, name="Bag", price=1)
    mug = products[0]
    mug.category = other
    mug.save()
    assert mug.sort_order == 1
    # (saved again in the same category, it keeps its place)
    mug.name = "Big mug"
    mug.save()
    assert mug.sort_order == 1


def test_live_products_in_order(category, products):
    for product in products:
        baker.make("shop.ProductVariant", product=product)
    Product.objects.filter(name="Calendar").update(sort_order=-1)
    assert [p.name for p in category.live_products] == ["Calendar", "Mug", "Card"]


def reorder_url(category, product, position):
    url = reverse("shop_category_products_reorder", args=(category.pk, product.pk))
    return f"{url}?position={position}"


def test_reorder_products(admin_client, category, products):
    mug, card, calendar = products
    resp = admin_client.post(reorder_url(category, calendar, 0))
    assert resp.json() == {"success": True}
    assert names(category) == ["Calendar", "Mug", "Card"]
    admin_client.post(reorder_url(category, calendar, 2))
    assert names(category) == ["Mug", "Card", "Calendar"]


def test_reorder_product_from_another_category(admin_client, category, products):
    other = baker.make("shop.Category", title="Other")
    bag = Product.objects.create(category=other, name="Bag", price=1)
    resp = admin_client.post(reorder_url(category, bag, 0))
    assert resp.status_code == 404


def test_reorder_needs_permission(client, category, products):
    user = baker.make("auth.User")
    user.groups.add(Group.objects.get(name="Shop manager"))
    client.force_login(user)
    admin_client_resp = client.post(reorder_url(category, products[2], 0))
    assert admin_client_resp.status_code == 302
    assert names(category) == ["Mug", "Card", "Calendar"]


def edit_page(client, category):
    url = reverse("wagtailsnippets_shop_category:edit", args=(category.pk,))
    return html.unescape(client.get(url).content.decode())


def test_category_page_products(client, category, products):
    user = baker.make("auth.User")
    user.groups.add(Group.objects.get(name="Shop admins"))
    client.force_login(user)
    content = edit_page(client, category)
    assert content.count('data-w-orderable-target="item"') == 3
    shown = re.findall(r">\s*(Mug|Card|Calendar)\s*<", content)
    assert shown == ["Mug", "Card", "Calendar"]
    assert reverse("shop_category_products_reorder", args=(category.pk, 999999)) in content
    assert "Drag them" in content
    assert reverse("wagtailsnippets_shop_product:edit", args=(products[0].pk,)) in content


def test_category_page_one_product(admin_client, category):
    # nothing to reorder
    Product.objects.create(category=category, name="Mug", price=1)
    content = edit_page(admin_client, category)
    assert re.search(r">\s*Mug\s*<", content)
    assert "Drag them" not in content
    assert "data-w-orderable-url-value" not in content


def test_category_page_no_products(admin_client, category):
    assert "There are no products in this category yet." in edit_page(admin_client, category)


def test_new_category_page(admin_client):
    content = html.unescape(
        admin_client.get(reverse("wagtailsnippets_shop_category:add")).content.decode()
    )
    assert "Once the category has been saved, its products are listed here" in content


def test_categories_list_products_link(admin_client, category, products):
    content = admin_client.get(reverse("wagtailsnippets_shop_category:list")).content.decode()
    url = reverse("wagtailsnippets_shop_product:list")
    assert f'<a href="{url}?category={category.pk}">0 live (3 total)</a>' in content
