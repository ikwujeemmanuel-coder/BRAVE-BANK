"""Tests for database configuration guard, email linking, notifications, and support tickets."""

from decimal import Decimal
from fastapi.testclient import TestClient

import pytest

from backend.app.database import DatabaseConfigurationError, get_db, normalize_postgres_url
from backend.app.main import create_app
from backend.tests.conftest import register_and_verify_user


def test_sqlite_and_missing_database_url_are_rejected():
    with pytest.raises(DatabaseConfigurationError):
        normalize_postgres_url(None)
    with pytest.raises(DatabaseConfigurationError):
        normalize_postgres_url("sqlite:///./local.db")


def test_email_linking_notifications_and_support_tickets(client):
    user = register_and_verify_user(client, phone_number="08188887777", pin="9876")
    headers = user["headers"]

    # Link optional email and verify with dev OTP
    link = client.post(
        "/api/auth/email/link",
        json={"email": "customer@bravebank.ng"},
        headers=headers,
    )
    assert link.status_code == 200
    verify = client.post(
        "/api/auth/email/verify",
        json={"otp_code": link.json()["dev_otp"]},
        headers=headers,
    )
    assert verify.status_code == 200
    assert verify.json()["email"] == "customer@bravebank.ng"

    # Notifications exist from welcome + email verification
    notifs = client.get("/api/notifications", headers=headers).json()
    assert len(notifs) >= 2
    assert client.post("/api/notifications/read-all", headers=headers).status_code == 200

    # Support ticket & FAQs
    faqs = client.get("/api/support/faqs").json()
    assert len(faqs) >= 3

    ticket = client.post(
        "/api/support/tickets",
        json={
            "category": "transfers",
            "subject": "Transfer receipt inquiry",
            "message": "Please confirm how to export my transfer receipt.",
        },
        headers=headers,
    )
    assert ticket.status_code == 201
    assert ticket.json()["reference"].startswith("SUP-")

    # Unauthenticated private route denied
    assert client.get("/api/accounts/dashboard").status_code == 401


def test_multi_customer_isolation_and_persistence_across_restart(client, db_session):
    alice = register_and_verify_user(
        client,
        phone_number="08070001111",
        first_name="Ngozi",
        surname="Eze",
        password="NgoziPass#1",
        pin="1122",
    )
    bob = register_and_verify_user(
        client,
        phone_number="08070002222",
        first_name="Ibrahim",
        surname="Musa",
        password="IbrahimPass#2",
        pin="4455",
    )

    # Customer A funds account, creates card, beneficiary, goal, ticket
    dep = client.post("/api/accounts/deposit", json={"amount": "75000.00"}, headers=alice["headers"])
    assert dep.status_code == 201
    card_a = client.post("/api/cards", json={"label": "Ngozi Main"}, headers=alice["headers"]).json()
    ben_a = client.post(
        "/api/transfers/beneficiaries",
        json={
            "nickname": "A Vendor",
            "account_number": "0123456789",
            "account_name": "VENDOR ONE",
            "bank_code": "058",
            "bank_name": "GTBank",
            "is_internal": False,
        },
        headers=alice["headers"],
    ).json()
    goal_a = client.post(
        "/api/savings/goals",
        json={"title": "Emergency Fund", "target_amount": "150000.00"},
        headers=alice["headers"],
    ).json()
    client.post(
        "/api/savings/contribute",
        json={"goal_id": goal_a["id"], "amount": "15000.00", "pin": "1122"},
        headers=alice["headers"],
    )

    # Customer B cannot see or mutate Customer A's records
    assert client.get("/api/cards", headers=bob["headers"]).json() == []
    assert client.post(f"/api/cards/{card_a['id']}/toggle-freeze", headers=bob["headers"]).status_code == 404
    assert client.delete(f"/api/transfers/beneficiaries/{ben_a['id']}", headers=bob["headers"]).status_code == 404
    assert Decimal(client.get("/api/accounts/me", headers=bob["headers"]).json()["available_balance"]) == Decimal("0.00")

    # Logout Customer A, rebuild fresh FastAPI app instance (simulating restart), log back in
    assert client.post("/api/auth/logout", headers=alice["headers"]).status_code == 200

    restarted_app = create_app()
    restarted_app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(restarted_app) as fresh_client:
        login = fresh_client.post(
            "/api/auth/login",
            json={"phone_number": "08070001111", "password": "NgoziPass#1"},
        )
        assert login.status_code == 200
        fresh_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        dash = fresh_client.get("/api/accounts/dashboard", headers=fresh_headers).json()
        assert dash["account"]["account_number"] == alice["account_number"]
        assert Decimal(dash["account"]["available_balance"]) == Decimal("60000.00")
        assert Decimal(dash["savings_summary"]["balance"]) == Decimal("15000.00")
        assert dash["secondary_currency"]["currency"] == "USD"
        assert dash["secondary_currency"]["enabled"] is False
        assert len(fresh_client.get("/api/cards", headers=fresh_headers).json()) == 1
