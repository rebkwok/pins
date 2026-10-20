"""
Checks for the issues Wagtail's accessibility checker (shown to admins in the
userbar) reports on shop pages: empty buttons and headings, and heading order.
"""
import re
from html.parser import HTMLParser

import pytest
from django.urls import reverse
from salesman.core.utils import get_salesman_model

pytestmark = pytest.mark.django_db

Order = get_salesman_model("Order")


class HeadingParser(HTMLParser):
    """The page's headings, as (level, text)"""

    def __init__(self):
        super().__init__()
        self.headings = []
        self._level = None

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self._level = int(tag[1])
            self.headings.append([self._level, ""])

    def handle_endtag(self, tag):
        if re.fullmatch(r"h[1-6]", tag):
            self._level = None

    def handle_data(self, data):
        if self._level is not None:
            self.headings[-1][1] += data


def headings(content):
    parser = HeadingParser()
    parser.feed(content)
    return [(level, " ".join(text.split())) for level, text in parser.headings]


def main_headings(content):
    # the page's own content (not the site header or footer)
    return headings(content[content.index("<main>") : content.index("</main>")])


def check_headings(content, h1):
    found = main_headings(content)
    # one h1, with text; no empty headings; levels don't skip
    assert [text for level, text in found if level == 1] == [h1]
    assert all(text for _, text in found)
    levels = [level for level, _ in found]
    assert all(b <= a + 1 for a, b in zip(levels, levels[1:])), found


@pytest.mark.parametrize("new", [True, False])
def test_order_status_headings(client, order, new):
    url = reverse("shop:new_order_status" if new else "shop:order_status", args=(order.token,))
    content = client.get(url).content.decode()
    check_headings(content, "Order status")
    assert ("Thank you for your order!" in content) == new


def test_stripe_cancel_headings(client):
    content = client.get(reverse("stripe-connect-cancel")).content.decode()
    check_headings(content, "Payment cancelled")


def test_stripe_success_headings(client):
    content = client.get(reverse("stripe-connect-success")).content.decode()
    check_headings(content, "Order confirmed")
    assert "Thank you for your order!" in content


def test_basket_delete_button_label(client, basket):
    session = client.session
    session["BASKET_ID"] = basket.id
    session.save()
    content = client.get(reverse("shop:basket")).content.decode()
    # the button only has an icon, so it needs a label for screen readers
    assert 'aria-label="Remove Test Product - Small"' in content
    assert '<i class="fa-regular fa-trash-can" aria-hidden="true"></i>' in content
    check_headings(content, "Basket")
