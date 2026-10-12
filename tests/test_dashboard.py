"""Reporting boundaries, safe preferences, and navigable workspace views."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Client, Invoice, Payment, Project, Task
from app.services.common import setting
from app.services.reporting_service import financial_report


@pytest.mark.parametrize(
    "path", ["/dashboard", "/analytics", "/calendar", "/settings", "/search"]
)
def test_dashboard_pages_require_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.location


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/analytics",
        "/analytics/export.csv",
        "/calendar",
        "/settings",
        "/search",
    ],
)
def test_empty_workspace_pages_are_operational(auth_client, path):
    response = auth_client.get(path)
    assert response.status_code == 200, response.data.decode()[:2000]
    if path.endswith(".csv"):
        assert "text/csv" in response.content_type
    else:
        assert b"Hanami" in response.data


def test_settings_validate_before_write_and_convert_timezone(auth_client):
    response = auth_client.post(
        "/settings",
        data={
            "company_name": "Quiet Studio",
            "currency": "PHP",
            "business_timezone": "Not/AZone",
        },
    )
    assert response.status_code == 400
    assert setting("company_name", "absent") == "absent"
    response = auth_client.post(
        "/settings",
        data={
            "company_name": "Quiet Studio",
            "currency": "CAD",
            "business_timezone": "America/Toronto",
            "email_test_mode": "1",
            "automations_paused": "1",
        },
    )
    assert response.status_code == 302
    assert setting("company_name") == "Quiet Studio"
    assert setting("currency") == "CAD"
    assert setting("automations_paused") == "true"
    assert setting("email_test_mode") == "true"


def test_invalid_report_dates_are_rejected(auth_client):
    assert (
        auth_client.get("/analytics?start=2026-10-10&end=2026-10-01").status_code == 400
    )
    assert auth_client.get("/analytics?start=not-a-date").status_code == 400
    assert auth_client.get("/analytics?currency=XXX").status_code == 400
    assert auth_client.get("/calendar?month=2026-13").status_code == 400


def test_reports_separate_verified_receipts_currency_and_local_date(app):
    customer = Client(name="Owner", business_name="Fictional Studio")
    db.session.add(customer)
    db.session.flush()
    project = Project(client_id=customer.id, title="Website")
    db.session.add(project)
    db.session.flush()
    php = Invoice(
        reference="INV-PHP",
        project_id=project.id,
        client_id=customer.id,
        currency="PHP",
        issued_at=datetime(2026, 1, 31, 16, 0),
        total=Decimal("100.01"),
        status="issued",
    )
    usd = Invoice(
        reference="INV-USD",
        project_id=project.id,
        client_id=customer.id,
        currency="USD",
        issued_at=datetime(2026, 1, 31, 16, 0),
        total=Decimal("800.00"),
        status="issued",
    )
    draft = Invoice(
        reference="INV-DRAFT",
        project_id=project.id,
        client_id=customer.id,
        currency="PHP",
        total=Decimal("9000.00"),
        status="draft",
    )
    db.session.add_all([php, usd, draft])
    db.session.flush()
    db.session.add_all(
        [
            Payment(
                invoice_id=php.id,
                amount=Decimal("30.01"),
                method="Bank",
                reference="PAY-OK",
                verified=True,
                received_at=datetime(2026, 1, 31, 16, 30),
            ),
            Payment(
                invoice_id=php.id,
                amount=Decimal("70.00"),
                method="Bank",
                reference="PAY-PENDING",
                verified=False,
                received_at=datetime(2026, 2, 1, 5),
            ),
            Payment(
                invoice_id=usd.id,
                amount=Decimal("800.00"),
                method="Bank",
                reference="PAY-USD",
                verified=True,
                received_at=datetime(2026, 2, 1, 5),
            ),
        ]
    )
    db.session.commit()
    report = financial_report(date(2026, 2, 1), date(2026, 2, 28), "PHP")
    assert report["receipts"] == Decimal("30.01")
    assert report["invoiced"] == Decimal("100.01")
    assert report["outstanding"] == Decimal("70.00")
    assert report["monthly"][0]["receipts"] == Decimal("30.01")
    jan = financial_report(date(2026, 1, 1), date(2026, 1, 31), "PHP")
    assert jan["receipts"] == Decimal("0.00")
    assert jan["invoiced"] == Decimal("0.00")


def test_search_literal_wildcards_and_escapes_html(auth_client):
    db.session.add_all(
        [
            Client(name="<script>alert(1)</script>", business_name="100% Studio"),
            Client(name="Different", business_name="Other Studio"),
        ]
    )
    db.session.commit()
    response = auth_client.get("/search?q=%25")
    assert response.status_code == 200
    assert b"100% Studio" in response.data
    assert b"Other Studio" not in response.data
    response = auth_client.get("/search?q=%3Cscript%3E")
    assert b"<script>alert(1)</script>" not in response.data
    assert b"100% Studio" in response.data


def test_calendar_uses_business_timezone(auth_client):
    db.session.add(
        Task(title="Midnight task", due_at=datetime(2026, 1, 31, 16, 30), status="todo")
    )
    db.session.commit()
    response = auth_client.get("/calendar?month=2026-02")
    assert response.status_code == 200
    assert b"Midnight task" in response.data
    assert b"2026-02-01" in response.data
