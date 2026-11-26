"""Tests for 4-step Email-OTP registration, Nigerian phone validation, PIN setup, login, and JWT auth."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select

from backend.app.config import get_settings
from backend.app.models.banking import Account
from backend.app.models.user import OtpRecord, TransactionPin, User
from backend.app.security.hashing import hash_pin
from backend.app.services.email import get_dev_email_outbox
from backend.app.services.sms import get_dev_outbox
from backend.tests.conftest import (
    extract_latest_email_otp,
    extract_latest_sms_otp,
    register_and_verify_user,
)


def test_four_step_email_otp_registration_creates_account_and_preserves_phone_unverified(client, db_session):
    sms_before = len(get_dev_outbox("+2348031112233"))

    # Step 1: Personal details + required email (no PIN yet, no account yet)
    start_res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Aisha",
            "surname": "Bello",
            "phone_number": "08031112233",
            "email": "aisha.bello@example.com",
            "password": "Pass#12",
            "confirm_password": "Pass#12",
        },
    )
    assert start_res.status_code == 201, start_res.text
    start_data = start_res.json()
    assert start_data["step"] == "verify_email"
    assert start_data["phone_number"] == "+2348031112233"
    assert start_data["email"] == "aisha.bello@example.com"
    assert start_data["masked_email"] == "ai***o@example.com"
    assert "dev_otp" not in start_data

    # Registration OTP must ONLY go via email, never SMS
    assert len(get_dev_outbox("+2348031112233")) == sms_before
    email_outbox = get_dev_email_outbox("aisha.bello@example.com")
    assert email_outbox
    sent_otp = extract_latest_email_otp("aisha.bello@example.com")
    assert len(sent_otp) == 6
    assert sent_otp in email_outbox[0]["text_body"]

    # Incomplete registration cannot log in yet
    early_login = client.post(
        "/api/auth/login",
        json={"phone_number": "08031112233", "password": "Pass#12"},
    )
    assert early_login.status_code == 403

    # Step 2: Verify Email OTP -> marks email_verified=True ONLY, leaves phone_verified=False
    verify_res = client.post(
        "/api/auth/register/verify-email",
        json={"email": "aisha.bello@example.com", "code": sent_otp},
    )
    assert verify_res.status_code == 200, verify_res.text
    verify_data = verify_res.json()
    assert verify_data["step"] == "set_pin"
    assert verify_data["email_verified"] is True
    assert verify_data["phone_verified"] is False
    assert verify_data["registration_token"]

    # Still blocked from dashboard login until 4-digit PIN is created
    mid_login = client.post(
        "/api/auth/login",
        json={"phone_number": "08031112233", "password": "Pass#12"},
    )
    assert mid_login.status_code == 403

    # Step 3 & 4: Set 4-digit PIN -> creates unique 10-digit NGN account & authenticates session
    pin_res = client.post(
        "/api/auth/register/set-pin",
        json={
            "registration_token": verify_data["registration_token"],
            "pin": "2468",
            "confirm_pin": "2468",
        },
    )
    assert pin_res.status_code == 201, pin_res.text
    auth_data = pin_res.json()
    assert auth_data["user"]["email_verified"] is True
    assert auth_data["user"]["phone_verified"] is False
    assert auth_data["user"]["has_transaction_pin"] is True
    acct_no = auth_data["user"]["account_number"]
    assert len(acct_no) == 10 and acct_no.isdigit()


def test_required_email_password_strength_and_4_digit_pin_validation(client):
    # Missing email is rejected (422)
    missing_email = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Aisha",
            "surname": "Bello",
            "phone_number": "08031112233",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    )
    assert missing_email.status_code == 422

    # Too short (<7 chars)
    short_pw = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Aisha",
            "surname": "Bello",
            "phone_number": "08031112234",
            "email": "short@example.com",
            "password": "Ab#123",
            "confirm_password": "Ab#123",
        },
    )
    assert short_pw.status_code == 422

    # Missing symbol
    no_symbol = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Aisha",
            "surname": "Bello",
            "phone_number": "08031112235",
            "email": "nosymbol@example.com",
            "password": "Password123",
            "confirm_password": "Password123",
        },
    )
    assert no_symbol.status_code == 422

    # Start & verify valid user to test Step 3 PIN constraints
    start = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Aisha",
            "surname": "Bello",
            "phone_number": "08031112236",
            "email": "pincheck@example.com",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    ).json()
    reg_token = client.post(
        "/api/auth/register/verify-email",
        json={"email": start["email"], "code": extract_latest_email_otp(start["email"])},
    ).json()["registration_token"]

    for bad_pin in ["123", "12345", "123456", "12a4", "1 23"]:
        res = client.post(
            "/api/auth/register/set-pin",
            json={"registration_token": reg_token, "pin": bad_pin, "confirm_pin": bad_pin},
        )
        assert res.status_code == 422, f"Expected 422 for PIN {bad_pin!r}"

    bad_match = client.post(
        "/api/auth/register/set-pin",
        json={"registration_token": reg_token, "pin": "1234", "confirm_pin": "5678"},
    )
    assert bad_match.status_code == 422

    # Leading-zero 4-digit PIN ("0123") must succeed and authorize transactions
    zero_user = register_and_verify_user(
        client, phone_number="08031112239", password="Password#123", pin="0123"
    )
    client.post("/api/accounts/deposit", json={"amount": "10000.00"}, headers=zero_user["headers"])
    wdr = client.post(
        "/api/accounts/withdraw",
        json={"amount": "2500.00", "pin": "0123"},
        headers=zero_user["headers"],
    )
    assert wdr.status_code == 201


def test_duplicate_phone_and_email_registration_rejected(client):
    register_and_verify_user(client, phone_number="08099990001", email="dupcheck@example.com")
    dup_phone = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Other",
            "surname": "User",
            "phone_number": "+2348099990001",
            "email": "other@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
    )
    assert dup_phone.status_code == 409

    dup_email = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Other",
            "surname": "User",
            "phone_number": "08099990002",
            "email": "DUPCHECK@EXAMPLE.COM",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
    )
    assert dup_email.status_code == 409


def test_pending_registration_retry_and_resume_without_duplicates(client, db_session):
    first = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Chidi",
            "surname": "Nwosu",
            "phone_number": "08055551234",
            "email": "chidi.nwosu@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
    )
    assert first.status_code == 201
    assert db_session.scalar(select(func.count(User.id))) == 1

    # Resume with valid credentials returns verify_email step cleanly without duplicating users
    resume1 = client.post(
        "/api/auth/register/resume",
        json={"phone_number": "08055551234", "password": "Password123!"},
    )
    assert resume1.status_code == 200
    assert resume1.json()["step"] == "verify_email"
    assert db_session.scalar(select(func.count(User.id))) == 1

    # Verify email, then resume again -> transitions cleanly to set_pin step
    verify = client.post(
        "/api/auth/register/verify-email",
        json={
            "email": "chidi.nwosu@example.com",
            "code": extract_latest_email_otp("chidi.nwosu@example.com"),
        },
    )
    assert verify.status_code == 200

    resume2 = client.post(
        "/api/auth/register/resume",
        json={"phone_number": "08055551234", "password": "Password123!"},
    )
    assert resume2.status_code == 200
    assert resume2.json()["step"] == "set_pin"
    assert resume2.json()["registration_token"]
    assert db_session.scalar(select(func.count(User.id))) == 1


def test_invalid_nigerian_phone_rejected(client):
    res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Test",
            "surname": "User",
            "phone_number": "+14155552671",
            "email": "intl@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
    )
    assert res.status_code == 422


def test_email_otp_cooldown_attempts_and_expiry(client, db_session):
    reg = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Tunde",
            "surname": "Adeyemi",
            "phone_number": "08122223344",
            "email": "tunde.otp@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
    ).json()

    assert "dev_otp" not in reg
    first_otp = extract_latest_email_otp("tunde.otp@example.com")

    # Cooldown prevents immediate resend
    resend = client.post(
        "/api/auth/register/resend-email-otp",
        json={"email": "tunde.otp@example.com"},
    )
    assert resend.status_code == 429

    # Wrong OTP increments attempts up to 5 and invalidates
    for _ in range(5):
        bad = client.post(
            "/api/auth/register/verify-email",
            json={"email": "tunde.otp@example.com", "code": "000000"},
        )
        assert bad.status_code == 400

    # Even real OTP now fails because max attempts exceeded
    real_after_lock = client.post(
        "/api/auth/register/verify-email",
        json={"email": "tunde.otp@example.com", "code": first_otp},
    )
    assert real_after_lock.status_code == 400

    # Reset last_sent_at to bypass cooldown and test expiry
    latest = db_session.scalar(
        select(OtpRecord)
        .where(OtpRecord.target_email == "tunde.otp@example.com")
        .order_by(desc(OtpRecord.created_at))
    )
    latest.last_sent_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    db_session.commit()

    fresh = client.post(
        "/api/auth/register/resend-email-otp",
        json={"email": "tunde.otp@example.com"},
    )
    assert fresh.status_code == 200
    assert "dev_otp" not in fresh.json()
    fresh_otp = extract_latest_email_otp("tunde.otp@example.com")

    # Expire the OTP manually in DB
    newest = db_session.scalar(
        select(OtpRecord)
        .where(OtpRecord.target_email == "tunde.otp@example.com", OtpRecord.invalidated_at.is_(None))
        .order_by(desc(OtpRecord.created_at))
    )
    newest.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    expired_res = client.post(
        "/api/auth/register/verify-email",
        json={"email": "tunde.otp@example.com", "code": fresh_otp},
    )
    assert expired_res.status_code == 400
    assert "expired" in expired_res.json()["detail"].lower()


def test_production_unconfigured_email_fails_loudly(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMAIL_PROVIDER", "brevo")
    monkeypatch.setenv("BREVO_API_KEY", "")
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "")
    get_settings.cache_clear()
    try:
        res = client.post(
            "/api/auth/register/start",
            json={
                "first_name": "Prod",
                "surname": "Test",
                "phone_number": "08077778888",
                "email": "prod@example.com",
                "password": "Password123!",
                "confirm_password": "Password123!",
            },
        )
        assert res.status_code == 503
        assert "not configured" in res.json()["detail"].lower() or "credentials" in res.json()["detail"].lower()
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("EMAIL_PROVIDER", "mock")
        get_settings.cache_clear()


def test_login_phone_variants_rejections_and_no_duplicates(client, db_session):
    customer = register_and_verify_user(client, phone_number="09122147173", password="MyPassword99!")
    user_count_before = db_session.scalar(select(func.count(User.id)))
    acct_count_before = db_session.scalar(select(func.count(Account.id)))

    # Incorrect password rejected
    bad_pw = client.post(
        "/api/auth/login",
        json={"phone_number": "09122147173", "password": "WrongPassword#1"},
    )
    assert bad_pw.status_code == 401

    # Unknown phone rejected
    unknown = client.post(
        "/api/auth/login",
        json={"phone_number": "08099887766", "password": "MyPassword99!"},
    )
    assert unknown.status_code == 401

    # Valid login works with 091..., +23491..., or 10-digit 91... without creating duplicates
    headers = {}
    for variant in ["09122147173", "+2349122147173", "9122147173"]:
        login_res = client.post(
            "/api/auth/login",
            json={"phone_number": variant, "password": "MyPassword99!"},
        )
        assert login_res.status_code == 200, login_res.text
        tokens = login_res.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["account_number"] == customer["account_number"]

    assert db_session.scalar(select(func.count(User.id))) == user_count_before
    assert db_session.scalar(select(func.count(Account.id))) == acct_count_before

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 200
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_httponly_cookie_session_and_csrf_and_https_partitioned(client):
    customer = register_and_verify_user(client, phone_number="07011113333", password="CookiePass#99")

    # 1. Proxied HTTPS login emits Secure; SameSite=none; Partitioned cookies
    https_login = client.post(
        "/api/auth/login",
        json={"phone_number": "07011113333", "password": "CookiePass#99"},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert https_login.status_code == 200
    set_cookie_headers = https_login.headers.get_list("set-cookie")
    assert any("SameSite=none" in h or "SameSite=None" in h for h in set_cookie_headers)
    assert any("Secure" in h for h in set_cookie_headers)
    assert any("Partitioned" in h for h in set_cookie_headers)
    client.cookies.clear()

    # 2. Local HTTP login works with SameSite=Lax cookies + CSRF enforcement
    login_res = client.post(
        "/api/auth/login",
        json={"phone_number": "07011113333", "password": "CookiePass#99"},
    )
    assert login_res.status_code == 200
    assert "bb_access_token" in client.cookies
    assert "bb_csrf_token" in client.cookies

    # Safe GET works via HttpOnly cookie without Authorization header
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["account_number"] == customer["account_number"]

    # Mutating POST via cookie without X-CSRF-Token is rejected (403)
    no_csrf = client.post("/api/accounts/deposit", json={"amount": "1000.00"})
    assert no_csrf.status_code == 403

    # Mutating POST with matching X-CSRF-Token succeeds
    csrf_token = client.cookies.get("bb_csrf_token")
    with_csrf = client.post(
        "/api/accounts/deposit",
        json={"amount": "1000.00"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert with_csrf.status_code == 201

    # Logout via cookie + CSRF revokes session and clears cookies
    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_legacy_6_digit_pin_upgrade_and_otp_pin_reset(client, db_session):
    customer = register_and_verify_user(client, phone_number="08061112222", pin="1234")
    # Simulate an existing customer whose DB row still holds a legacy 6-digit Argon2 PIN hash
    pin_row = db_session.scalar(
        select(TransactionPin).where(TransactionPin.user_id == customer["user"]["id"])
    )
    pin_row.pin_hash = hash_pin("654321")
    db_session.commit()

    # Upgrading from preserved 6-digit PIN ("654321") to 4-digit PIN ("0987") succeeds
    upgrade = client.post(
        "/api/auth/pin/change",
        json={"current_pin": "654321", "new_pin": "0987", "confirm_pin": "0987"},
        headers=customer["headers"],
    )
    assert upgrade.status_code == 200

    # OTP PIN reset sends to verified email and establishes a new 4-digit PIN ("4321")
    reset_req = client.post("/api/auth/pin/reset-request", headers=customer["headers"])
    assert reset_req.status_code == 200
    assert "dev_otp" not in reset_req.json()
    assert reset_req.json()["masked_email"]
    reset_confirm = client.post(
        "/api/auth/pin/reset-confirm",
        json={
            "otp_code": extract_latest_email_otp(customer["user"]["email"]),
            "new_pin": "4321",
            "confirm_pin": "4321",
        },
        headers=customer["headers"],
    )
    assert reset_confirm.status_code == 200

    client.post("/api/accounts/deposit", json={"amount": "5000.00"}, headers=customer["headers"])
    wdr = client.post(
        "/api/accounts/withdraw",
        json={"amount": "1000.00", "pin": "4321"},
        headers=customer["headers"],
    )
    assert wdr.status_code == 201


def test_cross_origin_csrf_bootstrap_refresh_rotation_and_expired_session(client, db_session):
    from backend.app.models.user import LoginSession
    from backend.app.security.jwt import create_access_token

    customer = register_and_verify_user(client, phone_number="08081112222", password="CrossOrigin#1")
    https_base = "https://testserver"

    # 1. HTTPS login returns matching csrf_token and sets Partitioned cookies
    login_res = client.post(
        f"{https_base}/api/auth/login",
        json={"phone_number": "08081112222", "password": "CrossOrigin#1"},
        headers={"X-Forwarded-Proto": "https", "Origin": "https://bravebank-frontend.onrender.com"},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["csrf_token"]
    assert login_data["csrf_token"] == client.cookies.get("bb_csrf_token")
    assert login_res.headers.get("access-control-allow-origin") == "https://bravebank-frontend.onrender.com"
    assert login_res.headers.get("access-control-allow-credentials") == "true"

    # 2. Cross-origin CSRF bootstrap returns the exact token matching the cookie
    csrf_res = client.get(
        f"{https_base}/api/auth/csrf",
        headers={"X-Forwarded-Proto": "https", "Origin": "https://bravebank-frontend.onrender.com"},
    )
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]
    assert csrf_token == client.cookies.get("bb_csrf_token")

    # Mismatched CSRF fails (403); matching X-CSRF-Token succeeds (201)
    bad_csrf = client.post(
        f"{https_base}/api/accounts/deposit",
        json={"amount": "2000.00"},
        headers={"X-CSRF-Token": "wrong-token", "Origin": "https://bravebank-frontend.onrender.com"},
    )
    assert bad_csrf.status_code == 403

    good_csrf = client.post(
        f"{https_base}/api/accounts/deposit",
        json={"amount": "2000.00"},
        headers={"X-CSRF-Token": csrf_token, "Origin": "https://bravebank-frontend.onrender.com"},
    )
    assert good_csrf.status_code == 201

    # 3. Refresh via HttpOnly cookie rotates tokens and revokes the previous refresh token
    old_refresh = client.cookies.get("bb_refresh_token")
    assert old_refresh
    refresh_res = client.post(
        f"{https_base}/api/auth/refresh",
        json={},
        headers={"X-Forwarded-Proto": "https", "Origin": "https://bravebank-frontend.onrender.com"},
    )
    assert refresh_res.status_code == 200
    refresh_data = refresh_res.json()
    assert refresh_data["access_token"] != login_data["access_token"]
    assert refresh_data["refresh_token"] != old_refresh
    assert refresh_data["csrf_token"] == client.cookies.get("bb_csrf_token")

    # Replaying old refresh token is rejected (401)
    replay_res = client.post(f"{https_base}/api/auth/refresh", json={"refresh_token": old_refresh})
    assert replay_res.status_code == 401

    # 4. Expired session in DB rejects access token and refresh
    active_sessions = db_session.scalars(
        select(LoginSession).where(
            LoginSession.user_id == customer["user"]["id"],
            LoginSession.revoked_at.is_(None),
        )
    ).all()
    assert len(active_sessions) >= 1
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    for sess in active_sessions:
        sess.expires_at = expired_at
    db_session.commit()

    expired_access = create_access_token(customer["user"]["id"], active_sessions[-1].id)
    assert (
        client.get(
            f"{https_base}/api/auth/me", headers={"Authorization": f"Bearer {expired_access}"}
        ).status_code
        == 401
    )
    assert client.post(f"{https_base}/api/auth/refresh", json={}).status_code == 401

