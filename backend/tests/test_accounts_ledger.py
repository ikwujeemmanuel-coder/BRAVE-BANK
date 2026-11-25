"""Tests for deposits, withdrawals, atomic internal transfers, idempotency, and ledger integrity."""

from decimal import Decimal

from sqlalchemy import select

from backend.app.models.banking import Account, LedgerEntry, Transaction
from backend.tests.conftest import register_and_verify_user


def test_deposit_withdrawal_and_insufficient_balance(client, db_session):
    customer = register_and_verify_user(client, phone_number="08055551111", pin="1122")
    headers = customer["headers"]

    dep = client.post(
        "/api/accounts/deposit",
        json={"amount": "50000.00", "narration": "Opening funding", "idempotency_key": "dep-key-1"},
        headers=headers,
    )
    assert dep.status_code == 201
    assert Decimal(dep.json()["amount"]) == Decimal("50000.00")

    # Duplicate idempotency key returns original transaction without double-crediting
    dup_dep = client.post(
        "/api/accounts/deposit",
        json={"amount": "50000.00", "narration": "Opening funding", "idempotency_key": "dep-key-1"},
        headers=headers,
    )
    assert dup_dep.status_code == 201
    assert dup_dep.json()["reference"] == dep.json()["reference"]

    # Withdrawal succeeds
    wdr = client.post(
        "/api/accounts/withdraw",
        json={"amount": "15000.00", "pin": "1122", "narration": "ATM test"},
        headers=headers,
    )
    assert wdr.status_code == 201

    # Over-withdrawal fails cleanly without altering balance
    fail_wdr = client.post(
        "/api/accounts/withdraw",
        json={"amount": "90000.00", "pin": "1122", "narration": "Too large"},
        headers=headers,
    )
    assert fail_wdr.status_code == 400

    acct_res = client.get("/api/accounts/me", headers=headers)
    assert Decimal(acct_res.json()["available_balance"]) == Decimal("35000.00")

    # Verify ledger entry consistency in PostgreSQL
    acct_row = db_session.scalar(
        select(Account).where(Account.account_number == customer["account_number"])
    )
    entries = db_session.scalars(
        select(LedgerEntry).where(LedgerEntry.account_id == acct_row.id)
    ).all()
    assert len(entries) == 2
    net = sum(
        e.amount if e.entry_type == "credit" else -e.amount
        for e in entries
    )
    assert net == Decimal("35000.00")


def test_internal_transfer_atomicity_and_history_isolation(client, db_session):
    alice = register_and_verify_user(
        client, phone_number="08033330001", first_name="Alice", surname="Nwachukwu", pin="1234"
    )
    bob = register_and_verify_user(
        client, phone_number="08033330002", first_name="Bob", surname="Danladi", pin="6543"
    )

    client.post(
        "/api/accounts/deposit",
        json={"amount": "40000.00", "narration": "Salary"},
        headers=alice["headers"],
    )

    lookup = client.get(
        f"/api/transfers/lookup-internal?query={bob['account_number']}",
        headers=alice["headers"],
    )
    assert lookup.status_code == 200
    assert lookup.json()["account_number"] == bob["account_number"]

    trf = client.post(
        "/api/transfers/internal",
        json={
            "recipient_account_number": bob["account_number"],
            "amount": "12500.50",
            "pin": "1234",
            "narration": "Rent split",
            "idempotency_key": "trf-alice-bob-1",
        },
        headers=alice["headers"],
    )
    assert trf.status_code == 201
    tx_id = trf.json()["id"]

    alice_acct = client.get("/api/accounts/me", headers=alice["headers"]).json()
    bob_acct = client.get("/api/accounts/me", headers=bob["headers"]).json()
    assert Decimal(alice_acct["available_balance"]) == Decimal("27499.50")
    assert Decimal(bob_acct["available_balance"]) == Decimal("12500.50")

    # Bob cannot fetch Alice's debit transaction receipt
    cross = client.get(f"/api/transactions/{tx_id}", headers=bob["headers"])
    assert cross.status_code == 404

    # Alice sees both deposit and transfer in history
    hist = client.get("/api/transactions?category=internal_transfer", headers=alice["headers"]).json()
    assert hist["total"] == 1
    assert hist["items"][0]["narration"] == "Rent split"

    # Total ledger check across both accounts
    all_txs = db_session.scalars(select(Transaction)).all()
    assert len(all_txs) == 3
