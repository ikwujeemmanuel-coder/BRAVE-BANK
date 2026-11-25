"""Tests for external transfers, beneficiaries, savings goals, virtual cards, and bill payments."""

from decimal import Decimal

from sqlalchemy import select

from backend.app.models.services import SavingsContribution
from backend.tests.conftest import register_and_verify_user


def test_beneficiaries_and_external_transfer(client, db_session):
    from backend.app.models.banking import Transaction

    user = register_and_verify_user(client, phone_number="08044440001", pin="1357")
    headers = user["headers"]

    client.post("/api/accounts/deposit", json={"amount": "60000.00"}, headers=headers)
    bal_before = Decimal(client.get("/api/accounts/me", headers=headers).json()["available_balance"])
    assert bal_before == Decimal("560000.00")

    banks = client.get("/api/transfers/banks", headers=headers).json()
    assert len(banks) >= 5

    resolved = client.post(
        "/api/transfers/external/resolve",
        json={"bank_code": "058", "account_number": "0123456789"},
        headers=headers,
    )
    assert resolved.status_code == 200
    acct_name = resolved.json()["account_name"]

    ben = client.post(
        "/api/transfers/beneficiaries",
        json={
            "nickname": "GTB Vendor",
            "account_number": "0123456789",
            "account_name": acct_name,
            "bank_code": "058",
            "bank_name": "Guaranty Trust Bank (GTBank)",
            "is_internal": False,
        },
        headers=headers,
    )
    assert ben.status_code == 201
    ben_id = ben.json()["id"]

    ext = client.post(
        "/api/transfers/external",
        json={
            "bank_code": "058",
            "account_number": "0123456789",
            "account_name": acct_name,
            "amount": "15000.00",
            "pin": "1357",
            "narration": "Supplier invoice",
        },
        headers=headers,
    )
    assert ext.status_code == 400
    assert ext.json()["detail"] == (
        "External bank transfers are currently unavailable. "
        "BraveBank cannot transfer real funds to other banks in this demo environment."
    )

    bal_after = Decimal(client.get("/api/accounts/me", headers=headers).json()["available_balance"])
    assert bal_after == bal_before
    ext_txs = db_session.scalars(
        select(Transaction).where(Transaction.category == "external_transfer")
    ).all()
    assert ext_txs == []

    bens = client.get("/api/transfers/beneficiaries", headers=headers).json()
    assert len(bens) == 1
    assert client.delete(f"/api/transfers/beneficiaries/{ben_id}", headers=headers).status_code == 200


def test_savings_goals_interest_bills_and_virtual_cards(client, db_session):
    user = register_and_verify_user(client, phone_number="09055550002", pin="2468")
    headers = user["headers"]

    client.post("/api/accounts/deposit", json={"amount": "100000.00"}, headers=headers)

    # Create savings goal and contribute
    goal_res = client.post(
        "/api/savings/goals",
        json={"title": "Laptop Upgrade", "target_amount": "200000.00"},
        headers=headers,
    )
    assert goal_res.status_code == 201
    goal_id = goal_res.json()["id"]

    contrib = client.post(
        "/api/savings/contribute",
        json={"goal_id": goal_id, "amount": "25000.00", "pin": "2468"},
        headers=headers,
    )
    assert contrib.status_code == 201
    assert Decimal(contrib.json()["savings_balance"]) == Decimal("25000.00")

    contrib_rows = db_session.scalars(select(SavingsContribution)).all()
    assert len(contrib_rows) == 1
    assert contrib_rows[0].amount == Decimal("25000.00")

    interest = client.post("/api/savings/simulate-interest", headers=headers)
    assert interest.status_code == 200
    assert Decimal(interest.json()["interest_credited"]) > Decimal("0.00")

    # Virtual card issue & freeze
    card = client.post(
        "/api/cards",
        json={"label": "Subscriptions", "brand": "Verve", "spending_limit": "50000.00"},
        headers=headers,
    )
    assert card.status_code == 201
    card_id = card.json()["id"]
    assert "••••" in card.json()["masked_pan"]

    freeze = client.post(f"/api/cards/{card_id}/toggle-freeze", headers=headers)
    assert freeze.status_code == 200
    assert freeze.json()["status"] == "frozen"

    # Bill payment
    bill = client.post(
        "/api/bills/pay",
        json={
            "category": "electricity",
            "provider": "IKEDC (Ikeja Electric)",
            "customer_reference": "45001122334",
            "amount": "5000.00",
            "pin": "2468",
        },
        headers=headers,
    )
    assert bill.status_code == 201
    assert bill.json()["token_or_receipt"].startswith("TOKEN-")

    # Dashboard exposes PostgreSQL weekly activity & savings summary
    dash = client.get("/api/accounts/dashboard", headers=headers)
    assert dash.status_code == 200
    dash_data = dash.json()
    assert len(dash_data["weekly_activity"]) == 7
    assert Decimal(dash_data["savings_summary"]["balance"]) >= Decimal("25000.00")
