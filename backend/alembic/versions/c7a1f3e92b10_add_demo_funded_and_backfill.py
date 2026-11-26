"""add demo_funded column and one-time 500k demo balance backfill

Revision ID: c7a1f3e92b10
Revises: 9849a9523842
Create Date: 2026-11-25 15:25:00.000000
"""

import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7a1f3e92b10"
down_revision: Union[str, Sequence[str], None] = "9849a9523842"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INITIAL_DEMO_AMOUNT = Decimal("500000.00")


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("demo_funded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    unfunded_accounts = conn.execute(
        sa.text(
            """
            SELECT a.id, a.user_id, a.account_number
            FROM accounts a
            WHERE a.demo_funded IS FALSE
              AND NOT EXISTS (
                  SELECT 1 FROM transactions t
                  WHERE t.idempotency_key = 'demo-init-' || a.id::text
              )
            ORDER BY a.created_at ASC
            """
        )
    ).fetchall()

    for row in unfunded_accounts:
        acct_id = row[0]
        user_id = row[1]
        account_number = row[2]

        updated = conn.execute(
            sa.text(
                """
                UPDATE accounts
                SET available_balance = available_balance + :amount,
                    ledger_balance = ledger_balance + :amount,
                    demo_funded = TRUE
                WHERE id = :acct_id AND demo_funded IS FALSE
                RETURNING available_balance
                """
            ),
            {"amount": INITIAL_DEMO_AMOUNT, "acct_id": acct_id},
        ).fetchone()

        if updated is None:
            continue

        balance_after = Decimal(updated[0])
        balance_before = balance_after - INITIAL_DEMO_AMOUNT
        tx_id = uuid.uuid4()
        ledger_id = uuid.uuid4()
        notif_id = uuid.uuid4()
        ref = f"DMO-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        idem_key = f"demo-init-{acct_id}"

        conn.execute(
            sa.text(
                """
                INSERT INTO transactions (
                    id, reference, idempotency_key, account_id, user_id,
                    category, direction, amount, fee, currency, status,
                    narration, counterparty_name, counterparty_account,
                    counterparty_bank, metadata_json, created_at
                ) VALUES (
                    :id, :reference, :idempotency_key, :account_id, :user_id,
                    'demo_funding', 'credit', :amount, 0.00, 'NGN', 'completed',
                    'Initial Demo Balance (Simulated Funds)', 'BRAVEBANK DEMO TREASURY', :account_number,
                    'BRAVEBANK (Simulated)', CAST(:metadata_json AS json), :created_at
                )
                """
            ),
            {
                "id": tx_id,
                "reference": ref,
                "idempotency_key": idem_key,
                "account_id": acct_id,
                "user_id": user_id,
                "amount": INITIAL_DEMO_AMOUNT,
                "account_number": account_number,
                "metadata_json": '{"simulated": true, "demo_initial_funding": true, "migrated_backfill": true}',
                "created_at": now,
            },
        )

        conn.execute(
            sa.text(
                """
                INSERT INTO ledger_entries (
                    id, transaction_id, account_id, entry_type,
                    amount, balance_before, balance_after, description, created_at
                ) VALUES (
                    :id, :transaction_id, :account_id, 'credit',
                    :amount, :balance_before, :balance_after,
                    'Initial Demo Balance (Simulated Funds)', :created_at
                )
                """
            ),
            {
                "id": ledger_id,
                "transaction_id": tx_id,
                "account_id": acct_id,
                "amount": INITIAL_DEMO_AMOUNT,
                "balance_before": balance_before,
                "balance_after": balance_after,
                "created_at": now,
            },
        )

        conn.execute(
            sa.text(
                """
                INSERT INTO notifications (
                    id, user_id, category, title, message, is_read, created_at
                ) VALUES (
                    :id, :user_id, 'transaction', 'Initial Demo Balance Credited',
                    :message, FALSE, :created_at
                )
                """
            ),
            {
                "id": notif_id,
                "user_id": user_id,
                "message": (
                    f"Your demo account {account_number} has been initialized with "
                    f"NGN {INITIAL_DEMO_AMOUNT:,.2f} in simulated funds. Ref: {ref}"
                ),
                "created_at": now,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    migrated_rows = conn.execute(
        sa.text(
            """
            SELECT id, account_id, user_id, reference
            FROM transactions
            WHERE idempotency_key LIKE 'demo-init-%'
              AND metadata_json ->> 'migrated_backfill' = 'true'
            """
        )
    ).fetchall()

    for row in migrated_rows:
        tx_id, acct_id, user_id, ref = row[0], row[1], row[2], row[3]
        conn.execute(
            sa.text("DELETE FROM ledger_entries WHERE transaction_id = :tx_id"),
            {"tx_id": tx_id},
        )
        conn.execute(
            sa.text("DELETE FROM transactions WHERE id = :tx_id"),
            {"tx_id": tx_id},
        )
        conn.execute(
            sa.text(
                "DELETE FROM notifications WHERE user_id = :user_id AND message LIKE :ref_like"
            ),
            {"user_id": user_id, "ref_like": f"%{ref}%"},
        )
        conn.execute(
            sa.text(
                """
                UPDATE accounts
                SET available_balance = available_balance - :amount,
                    ledger_balance = ledger_balance - :amount
                WHERE id = :acct_id
                """
            ),
            {"amount": INITIAL_DEMO_AMOUNT, "acct_id": acct_id},
        )

    op.drop_column("accounts", "demo_funded")
