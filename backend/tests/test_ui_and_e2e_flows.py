"""End-to-end tests for UI contract, static asset serving, design tokens, and complete banking journeys."""

from fastapi.testclient import TestClient

from backend.tests.conftest import register_and_verify_user


def test_frontend_static_assets_and_bravebank_ui_contract(client: TestClient):
    for asset_path in (
        "/",
        "/manifest.webmanifest",
        "/css/styles.css",
        "/js/app.js",
        "/js/logo.js",
        "/js/auth.js",
        "/js/registration.js",
        "/js/dashboard.js",
        "/js/transfers.js",
        "/js/bills.js",
        "/js/savings.js",
        "/js/cards.js",
        "/js/config.js",
        "/js/history.js",
        "/js/notifications.js",
        "/js/profile.js",
        "/js/views.js",
        "/js/ui.js",
        "/js/icons.js",
        "/js/api.js",
        "/js/state.js",
        "/assets/favicon.svg",
        "/assets/logo-star.svg",
        "/assets/pwa-icon.svg",
    ):
        res = client.get(asset_path)
        assert res.status_code == 200, f"Asset {asset_path} failed: {res.status_code}"

    html = client.get("/").text
    assert 'id="splash-screen"' in html
    assert "Banking Without Limits" in html
    assert 'id="welcome-view"' in html
    assert 'id="login-view"' in html
    assert 'id="register-view"' in html
    assert 'id="otp-form"' in html
    assert 'id="pin-setup-form"' in html
    assert "Verify Your Email" in html
    assert "Secure Your Account" in html
    assert 'id="otp-digit-grid"' in html
    assert html.count('class="otp-box"') == 6
    assert 'id="setup-pin"' in html
    assert 'maxlength="4"' in html  # 4-digit transaction PIN
    assert 'href="#"' not in html
    assert 'data-view="dashboard"' in html
    assert 'data-view="transfers"' in html
    assert 'data-view="cards"' in html
    assert 'data-view="history"' in html
    assert 'data-view="profile"' in html

    css = client.get("/css/styles.css").text
    assert "--primary: #007bff" in css.lower()
    assert "--secondary: #3390ff" in css.lower()
    assert "--navy: #0f172a" in css.lower()
    assert "--bg-light: #f3f6ff" in css.lower()
    assert "--white: #ffffff" in css.lower()

    dashboard_js = client.get("/js/dashboard.js").text
    for action_label in (
        "Transfer",
        "Add Money",
        "Withdraw",
        "Airtime",
        "Data",
        "Electricity",
        "TV",
        "Savings",
    ):
        assert action_label in dashboard_js

    config_js = client.get("/js/config.js").text
    assert "https://brave-bank.onrender.com" in config_js

    api_js = client.get("/js/api.js").text
    assert 'credentials: "include"' in api_js
    assert 'credentials: "same-origin"' not in api_js
    assert "buildApiUrl" in api_js


def test_complete_end_to_end_banking_journey_with_leading_zero_pin(client: TestClient):
    # 1. Register with a leading-zero 4-digit PIN and verify OTP
    customer = register_and_verify_user(
        client,
        phone_number="08123456789",
        first_name="Amina",
        surname="Bello",
        password="BraveUser!2026",
        pin="0123",
    )
    headers = customer["headers"]

    # 2. Dashboard reflects actual balance = 0.00 and zero invented transactions
    dash = client.get("/api/accounts/dashboard", headers=headers).json()
    assert dash["account"]["account_number"] == customer["account_number"]
    assert dash["account"]["available_balance"] == "0.00"
    assert dash["recent_transactions"] == []

    # 3. Add Money (Deposit)
    dep = client.post(
        "/api/accounts/deposit",
        headers=headers,
        json={"amount": "125750.00", "narration": "Initial Topup", "idempotency_key": "e2e-dep-1"},
    )
    assert dep.status_code == 201
    assert dep.json()["status"] == "completed"

    # 4. Withdraw using "0123" PIN
    wdr = client.post(
        "/api/accounts/withdraw",
        headers=headers,
        json={"amount": "5750.00", "pin": "0123", "narration": "ATM Cashout", "idempotency_key": "e2e-wdr-1"},
    )
    assert wdr.status_code == 201

    # 5. Pay all major Nigerian bill categories (Airtime, Data, Electricity, TV)
    for cat, provider, ref, amt in [
        ("airtime", "MTN Nigeria", "08123456789", "1000.00"),
        ("data", "Airtel Data", "08123456789", "2000.00"),
        ("electricity", "IKEDC (Ikeja Electric)", "45012349812", "5000.00"),
        ("television", "DStv", "7012345678", "9300.00"),
    ]:
        bill = client.post(
            "/api/bills/pay",
            headers=headers,
            json={
                "category": cat,
                "provider": provider,
                "customer_reference": ref,
                "amount": amt,
                "pin": "0123",
                "idempotency_key": f"e2e-bill-{cat}",
            },
        )
        assert bill.status_code == 201, bill.text
        assert bill.json()["token_or_receipt"]

    # 6. Verify balance updated accurately: 125750 - 5750 - 1000 - 2000 - 5000 - 9300 = 102700.00
    dash_after = client.get("/api/accounts/dashboard", headers=headers).json()
    assert dash_after["account"]["available_balance"] == "102700.00"

    # 7. Logout revokes Bearer/session access
    out = client.post("/api/auth/logout", headers=headers)
    assert out.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
