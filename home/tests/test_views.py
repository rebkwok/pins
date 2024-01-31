import csv
from decimal import Decimal
import io
from datetime import datetime

from django.urls import reverse
import openpyxl
import pytest


pytestmark = pytest.mark.django_db


def test_calculate_order_total_view(client, order_form_page):
    url = reverse("orders:calculate_order_total", args=(order_form_page.id,))
    resp = client.post(url, {"pv__test_product": 2})
    assert "<span id='order-total'>22.00</span>" in resp.content.decode()


def test_calculate_order_total_view_with_invalid_voucher(client, order_form_page):
    url = reverse("orders:calculate_order_total", args=(order_form_page.id,))
    resp = client.post(url, {"pv__test_product": 2, "voucher_code": "unk"})
    content = resp.content.decode()
    assert "<span id='order-total'>22.00</span>" in content
    assert "Voucher code unk is invalid" in content


def test_calculate_order_total_view_with_invalid_quantity(client, order_form_page):
    order_form_page.total_available = 2
    order_form_page.save()
    url = reverse("orders:calculate_order_total", args=(order_form_page.id,))
    resp = client.post(url, {"pv__test_product": 3})
    content = resp.content.decode()
    assert "<span id='order-total'>32.00</span>" in content
    assert "Quantity selected is unavailable" in content


def test_mark_order_form_submissions_paid(client, order_form_submission):
    s1 = order_form_submission()
    s2 = order_form_submission()
    s3 = order_form_submission()
    for s in [s1, s2, s3]:
        assert not s.paid
    client.get(reverse("orders:mark_order_form_submissions_paid"), {"selected-submissions": [s1.id, s2.id]})
    for s in [s1, s2, s3]:
        s.refresh_from_db()
    assert s1.paid
    assert s2.paid
    assert not s3.paid


def test_mark_order_form_submissions_shipped(client, order_form_submission):
    s1 = order_form_submission()
    s2 = order_form_submission()
    s3 = order_form_submission()
    for s in [s1, s2, s3]:
        assert not s.shipped
    client.get(reverse("orders:mark_order_form_submissions_shipped"), {"selected-submissions": [s1.id, s2.id]})
    for s in [s1, s2, s3]:
        s.refresh_from_db()
    assert s1.shipped
    assert s2.shipped
    assert not s3.paid


def test_reset_order_form_submissions(client, order_form_submission):
    s1 = order_form_submission()
    s2 = order_form_submission()
    for s in [s1, s2]:
        s.shipped = True
        s.paid = True
        s.save()
    
    client.get(reverse("orders:reset_order_form_submissions"), {"selected-submissions": [s1.id]})
    for s in [s1, s2]:
        s.refresh_from_db()
    assert not s1.shipped
    assert not s1.paid
    assert s2.shipped
    assert s2.paid


def test_order_detail(client, order_form_submission):
    submission = order_form_submission()
    assert not submission.paid
    resp = client.get(reverse("orders:order_detail", args=(submission.reference,)))

    assert "paypal_form" in resp.context_data
    assert resp.context_data["title"] == "Test"


def test_order_detail_paid(client, order_form_submission):
    submission = order_form_submission()
    submission.paid = True
    submission.save()
    resp = client.get(reverse("orders:order_detail", args=(submission.reference,)))

    assert "paypal_form" not in resp.context_data
    assert resp.context_data["title"] == "Test"


def test_order_form_submission_list_view(rf, admin_user, order_form_page, order_form_submission):
    submissions = [order_form_submission(), order_form_submission()]
    # reverse; submissions will be listed with most recent first
    submissions.reverse()
    request = rf.get("/")
    request.user = admin_user
    resp = order_form_page.serve_submissions_list_view(request)
    assert resp.context_data["description"] == f"Total sold: 4 | Remaining stock: N/A"

    heading_names_labels = [
        (heading["name"], heading["label"]) for heading in resp.context_data["data_headings"]
    ]
    assert heading_names_labels == [
        # default
        ("submit_time", "Submission date"),
        ("name", "name"),
        ("email_address", "email_address"),
        # reformatted product variant
        ("pv__test_product", "test product"),
        # extra fields
        ("reference", "Reference"),
        ("total", "Total (£)"),
        ("total_items", "Total items"),
        ("paid", "Paid"),
        ("shipped", "Shipped")
    ]

    data_rows = resp.context_data["data_rows"]
    assert len(data_rows) == 2
    for i, row in enumerate(data_rows):
        assert row["fields"][1:] == [
            "Mickey Mouse", "mickey.mouse@test.com", "2", submissions[i].reference, Decimal("22.00"), 2, "-", "-"
        ]


def test_order_form_submission_list_view_with_total_available(rf, admin_user, order_form_page, order_form_submission):
    order_form_page.total_available = 10
    order_form_page.save()
    order_form_submission()
    request = rf.get("/")
    request.user = admin_user
    resp = order_form_page.serve_submissions_list_view(request)
    assert resp.context_data["description"] == f"Total sold: 2 | Remaining stock: 8"


def test_order_form_submission_list_view_with_with_paid_and_shipped(rf, admin_user, order_form_page, order_form_submission):
    submissions = [order_form_submission(), order_form_submission(), order_form_submission()]
    # reverse; submissions will be listed with most recent first
    submissions.reverse()
    submissions[0].paid = True
    submissions[0].save()
    submissions[1].paid = True
    submissions[1].shipped = True
    submissions[1].save()

    request = rf.get("/")
    request.user = admin_user
    resp = order_form_page.serve_submissions_list_view(request)
    data_rows = resp.context_data["data_rows"]

    assert data_rows[0]["fields"][-2:] == ["Y", "-"]
    assert data_rows[1]["fields"][-2:] == ["Y", "Y"]
    assert data_rows[2]["fields"][-2:] == ["-", "-"]


@pytest.mark.freeze_time("2020-01-01")
def test_order_form_submission_list_view_write_xlsx(rf, admin_user, tmp_path, order_form_page, order_form_submission):
    submission = order_form_submission()
    request = request=rf.get("/?export=xlsx")
    request.user = admin_user
    resp = order_form_page.serve_submissions_list_view(request)
    wb = openpyxl.load_workbook(io.BytesIO(b"".join(resp.streaming_content)))
    sheet = wb.active
    values = [v for v in sheet.values]
    assert values == [
        ('Submission date', 'name', 'email_address', 'test product', 'Reference', 'Total (£)', 'Total items', 'Paid', 'Shipped'), 
        (datetime(2020, 1, 1), 'Mickey Mouse', 'mickey.mouse@test.com', '2', submission.reference, 22, 2, '-', '-')
    ]


@pytest.mark.freeze_time("2020-01-01")
def test_order_form_submission_list_view_write_csv(rf, admin_user, tmp_path, order_form_page, order_form_submission):
    submission = order_form_submission()
    request = request=rf.get("/?export=csv")
    request.user = admin_user
    resp = order_form_page.serve_submissions_list_view(request)
    csv_data = csv.reader(io.StringIO((b"".join(resp.streaming_content)).decode()))
    values = list(csv_data)
    assert values == [
        ['Submission date', 'name', 'email_address', 'test product', 'Reference', 'Total (£)', 'Total items', 'Paid', 'Shipped'], 
        ['2020-01-01 00:00:00+00:00', 'Mickey Mouse', 'mickey.mouse@test.com', '2', submission.reference, "22.00", "2", '-', '-']
    ]
