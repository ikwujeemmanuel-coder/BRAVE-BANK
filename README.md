# BRAVEBANK — Nigerian Digital Banking Prototype

BRAVEBANK is a full-stack simulated Nigerian digital banking web application built with **Python**, **FastAPI**, **SQLAlchemy**, **Alembic**, **PostgreSQL** (Neon in production), **HTML5**, **CSS3**, and **Vanilla JavaScript**.

> **Prototype Disclosure**: BRAVEBANK is a simulated digital banking prototype. Internal 10-digit account numbers, NGN balances, bank transfers, savings interest, virtual cards, and bill payments are simulated. No real money moves.

## Technology Stack

- **Backend**: Python 3.13, FastAPI, Pydantic / Pydantic Settings, PyJWT, Argon2 (`argon2-cffi`), `python-dotenv`, Pytest
- **Database & Migrations**: PostgreSQL (Neon PostgreSQL in production), SQLAlchemy 2.x (`NUMERIC(18, 2)` + Python `Decimal`), Alembic, `psycopg`
- **Frontend**: HTML5, CSS3, Vanilla JavaScript (ES Modules)
- **Deployment**: Render + Neon PostgreSQL

## Project Structure

```text
BRAVE-BANK/
├── backend/
│   ├── __init__.py
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/        # 18 SQLAlchemy PostgreSQL models
│   │   ├── schemas/       # Pydantic v2 validation schemas
│   │   ├── security/      # Argon2 hashing, PyJWT, HttpOnly cookies + CSRF, rate limiter
│   │   ├── services/      # Phone validation, Email/SMS providers, OTP, atomic ledger
│   │   └── routers/       # Modular FastAPI routers
│   └── tests/             # Pytest suite against isolated PostgreSQL DB
├── frontend/
│   ├── index.html
│   ├── manifest.webmanifest
│   ├── css/styles.css
│   ├── js/
│   │   ├── api.js
│   │   ├── app.js
│   │   ├── auth.js
│   │   ├── bills.js
│   │   ├── cards.js
│   │   ├── dashboard.js
│   │   ├── history.js
│   │   ├── icons.js
│   │   ├── logo.js
│   │   ├── notifications.js
│   │   ├── profile.js
│   │   ├── registration.js
│   │   ├── savings.js
│   │   ├── state.js
│   │   ├── transfers.js
│   │   ├── ui.js
│   │   └── views.js
│   └── assets/
│       ├── favicon.svg
│       ├── logo-star.svg
│       └── pwa-icon.svg
├── .env.example
├── .gitignore
├── .python-version
├── pytest.ini
├── render.yaml
├── requirements.txt
└── README.md
```

## Database Schema (PostgreSQL — 18 Tables)

1. `users` — Phone-first customer identity (`+234...`), required email for signup OTP, verification flags
2. `credentials` — Argon2id password hashes (min 7 chars + symbol) and failed-login lockout tracking
3. `transaction_pins` — Separately hashed Argon2id 4-digit transaction PINs configured during Step 3 of registration
4. `otp_records` — HMAC-hashed 6-digit email & SMS OTPs, 5-minute expiry, 5-attempt limit, 60s cooldown, invalidation
5. `login_sessions` — Hashed refresh tokens, user agent, IP, expiration, and revocation timestamps
6. `accounts` — Unique 10-digit BraveBank NGN accounts with `available_balance` and `ledger_balance`
7. `transactions` — Unique reference, idempotency key, category, direction, `NUMERIC(18,2)` amount/fee, metadata
8. `ledger_entries` — Double-entry style debit/credit ledger rows (`balance_before` -> `balance_after`)
9. `banks` — Seeded Nigerian bank directory (GTBank, First Bank, UBA, Access, Zenith, Kuda, OPay, etc.)
10. `beneficiaries` — Saved internal and external recipients per user
11. `savings_accounts` — Customer NGN savings vault balance, rate, and accrued interest
12. `savings_goals` — Named savings targets, progress amounts, and status
13. `savings_contributions` — Linked savings contribution records tied to ledger transactions
14. `virtual_cards` — Simulated Verve/Mastercard virtual cards with masked PANs and freeze/unfreeze state
15. `bill_payments` — Airtime, data, electricity, television, and education bill payment records & tokens
16. `notifications` — In-app transaction, security, and account alerts
17. `support_tickets` — Customer support ticket tracking and responses
18. `audit_logs` — Security and financial operation audit trail

## Local Startup Instructions

1. Ensure PostgreSQL is running and create two databases: `bravebank` and `bravebank_test`.
2. Create and activate a Python virtual environment, then install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set `DATABASE_URL`, `TEST_DATABASE_URL`, and `SECRET_KEY`.
4. Run Alembic database migrations:
   ```bash
   alembic -c backend/alembic.ini upgrade head
   ```
5. Start FastAPI with Uvicorn:
   ```bash
   uvicorn backend.app.main:app --host 0.0.0.0 --port 3000 --reload
   ```
6. Run the automated Pytest suite:
   ```bash
   pytest backend/tests -v
   ```

## Render + Neon PostgreSQL Deployment

1. Create a Neon PostgreSQL database and copy its `postgresql://...` connection string.
2. Push this repository to GitHub and create a new **Blueprint** or **Web Service** on Render using `render.yaml`.
3. Set the required secret environment variables in Render:
   - `DATABASE_URL`: Neon PostgreSQL connection string
   - `ALLOWED_ORIGINS`: Your Render app URL (e.g. `https://bravebank.onrender.com`)
4. Render executes `pip install -r requirements.txt && alembic -c backend/alembic.ini upgrade head` on build and starts Uvicorn on `$PORT`, verifying `/api/health`.
