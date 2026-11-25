"""Tests for initial demo balance, deposits, withdrawals, internal transfers, concurrency, and ledger integrity."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.database import get_db
from backend.app.main import create_app
from backend.app.models.banking import Account, LedgerEntry, Transaction
from backend.app.models.user import User
from backend.app.services.ledger import INITIAL_DEMO_BALANCE, credit_initial_demo_balance
from backend.tests.conftest import TestingSessionLocal, register_and_verify_user


def test_initial_demo_balance_idempotency_and_deposit_withdrawal(client, db_session):
    customer = register_and_verify_user(client, phone_number="08055551111", pin="1122")
    headers = customer["headers"]

    # Newly created account automatically starts with NGN 500,000.00 demo funds
    acct_initial = client.get("/api/accounts/me", headers=headers).json()
    assert Decimal(acct_initial["available_balance"]) == Decimal("500000.00")
    assert acct_initial["demo_funded"] is True

    # Calling credit_initial_demo_balance repeatedly or logging in again never double-credits
    acct_row = db_session.scalar(
        select(Account).where(Account.account_number == customer["account_number"])
    )
    user_row = db_session.get(User, acct_row.user_id)
    assert credit_initial_demo_balance(db_session, user_row, acct_row) is None
    db_session.refresh(acct_row)
    assert acct_row.available_balance == INITIAL_DEMO_BALANCE

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
        json={"amount": "900000.00", "pin": "1122", "narration": "Too large"},
        headers=headers,
    )
    assert fail_wdr.status_code == 400

    acct_res = client.get("/api/accounts/me", headers=headers)
    assert Decimal(acct_res.json()["available_balance"]) == Decimal("535000.00")

    # Verify ledger entry consistency in PostgreSQL (demo_funding + deposit + withdrawal = 3 entries)
    entries = db_session.scalars(
        select(LedgerEntry).where(LedgerEntry.account_id == acct_row.id)
    ).all()
    assert len(entries) == 3
    net = sum(
        e.amount if e.entry_type == "credit" else -e.amount
        for e in entries
    )
    assert net == Decimal("535000.00")


def test_internal_transfer_atomicity_validation_and_history_isolation(client, db_session):
    alice = register_and_verify_user(
        client, phone_number="08033330001", first_name="Alice", surname="Nwachukwu", pin="1234"
    )
    bob = register_and_verify_user(
        client, phone_number="08033330002", first_name="Bob", surname="Danladi", pin="6543"
    )
    charlie = register_and_verify_user(
        client, phone_number="08033330003", first_name="Charlie", surname="Okeke", pin="9988"
    )

    client.post(
        "/api/accounts/deposit",
        json={"amount": "40000.00", "narration": "Salary"},
        headers=alice["headers"],
    )

    # Lookup works by both 10-digit account number and Nigerian phone number
    lookup_acct = client.get(
        f"/api/transfers/lookup-internal?query={bob['account_number']}",
        headers=alice["headers"],
    )
    assert lookup_acct.status_code == 200
    assert lookup_acct.json()["account_number"] == bob["account_number"]

    lookup_phone = client.get(
        "/api/transfers/lookup-internal?query=08033330002",
        headers=alice["headers"],
    )
    assert lookup_phone.status_code == 200
    assert lookup_phone.json()["account_number"] == bob["account_number"]

    # Self-transfer lookup & execution rejected cleanly
    assert (
        client.get(
            f"/api/transfers/lookup-internal?query={alice['account_number']}",
            headers=alice["headers"],
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/transfers/internal",
            json={
                "recipient_account_number": alice["account_number"],
                "amount": "1000.00",
                "pin": "1234",
                "narration": "Self",
            },
            headers=alice["headers"],
        ).status_code
        == 400
    )

    # Inactive recipient rejected cleanly
    charlie_acct = db_session.scalar(
        select(Account).where(Account.account_number == charlie["account_number"])
    )
    charlie_acct.status = "frozen"
    db_session.commit()
    assert (
        client.get(
            f"/api/transfers/lookup-internal?query={charlie['account_number']}",
            headers=alice["headers"],
        ).status_code
        == 400
    )

    # Wrong PIN rejected cleanly without changing balance
    bad_pin = client.post(
        "/api/transfers/internal",
        json={
            "recipient_account_number": bob["account_number"],
            "amount": "5000.00",
            "pin": "0000",
            "narration": "Wrong PIN",
        },
        headers=alice["headers"],
    )
    assert bad_pin.status_code == 401

    # Valid transfer executes atomically
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
    assert Decimal(alice_acct["available_balance"]) == Decimal("527499.50")
    assert Decimal(bob_acct["available_balance"]) == Decimal("512500.50")

    # Bob cannot fetch Alice's debit transaction receipt
    cross = client.get(f"/api/transactions/{tx_id}", headers=bob["headers"])
    assert cross.status_code == 404

    # Alice sees transfer in history
    hist = client.get("/api/transactions?category=internal_transfer", headers=alice["headers"]).json()
    assert hist["total"] == 1
    assert hist["items"][0]["narration"] == "Rent split"

    # Total ledger check across all accounts:
    # 3 demo_funding + 1 alice deposit + 2 internal transfer legs = 6
    all_txs = db_session.scalars(select(Transaction)).all()
    assert len(all_txs) == 6


def test_concurrent_internal_transfers_prevent_double_spend(client):
    sender = register_and_verify_user(
        client, phone_number="08066660001", first_name="Tunde", surname="Bakare", pin="4321"
    )
    recipient = register_and_verify_user(
        client, phone_number="08066660002", first_name="Zainab", surname="Bello", pin="5678"
    )

    def _send_one(idx: int) -> int:
        local_app = create_app()

        def _override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        local_app.dependency_overrides[get_db] = _override_db
        with TestClient(local_app) as thread_client:
            res = thread_client.post(
                "/api/transfers/internal",
                json={
                    "recipient_account_number": recipient["account_number"],
                    "amount": "350000.00",
                    "pin": "4321",
                    "narration": f"Concurrent attempt {idx}",
                    "idempotency_key": f"race-key-{idx}",
                },
                headers=sender["headers"],
            )
            return res.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(_send_one, [1, 2]))

    assert sorted(statuses) == [201, 400]

    sender_bal = Decimal(client.get("/api/accounts/me", headers=sender["headers"]).json()["available_balance"])
    recipient_bal = Decimal(client.get("/api/accounts/me", headers=recipient["headers"]).json()["available_balance"])
    assert sender_bal == Decimal("150000.00")
    assert recipient_bal == Decimal("850000.00")

