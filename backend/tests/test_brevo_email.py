"""Automated tests for Brevo HTTP transactional email integration and OTP security."""

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re

import httpx
import pytest
from sqlalchemy import desc, func, select

from backend.app.config import get_settings
from backend.app.models.user import OtpRecord, TransactionPin, User
from backend.app.services import email as email_service
from backend.app.services.email import BREVO_OFFICIAL_ENDPOINT, EmailDeliveryError, send_otp_email


def _configure_brevo_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str = "xkeysib-test-secret-api-key-123456",
    from_name: str = "BraveBank",
    from_address: str = "no-reply@bravebank.ng",
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "brevo")
    monkeypatch.setenv("BREVO_API_KEY", api_key)
    monkeypatch.setenv("EMAIL_FROM_NAME", from_name)
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", from_address)
    get_settings.cache_clear()


_REAL_HTTPX_CLIENT = httpx.Client


def _mock_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    def _client_factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return _REAL_HTTPX_CLIENT(*args, transport=transport, **kwargs)

    monkeypatch.setattr(email_service.httpx, "Client", _client_factory)


@pytest.fixture(autouse=True)
def _restore_test_email_settings():
    yield
    get_settings.cache_clear()


def test_brevo_registration_payload_headers_endpoint_and_e2e_flow(client, db_session, monkeypatch, caplog):
    secret_key = "xkeysib-super-secret-do-not-leak-999"
    _configure_brevo_env(
        monkeypatch,
        api_key=secret_key,
        from_name="BraveBank",
        from_address="verified@bravebank.ng",
    )
    caplog.set_level(logging.DEBUG)

    captured_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "json": body,
            }
        )
        return httpx.Response(201, json={"messageId": "<20261126.reg@smtp-relay.mailin.fr>"})

    _mock_httpx_client(monkeypatch, handler)

    # 1. Start registration -> sends OTP through Brevo
    start_res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Zainab",
            "surname": "Usman",
            "phone_number": "08044445555",
            "email": "Zainab.Usman@example.com",
            "password": "BravePassword#1",
            "confirm_password": "BravePassword#1",
        },
    )
    assert start_res.status_code == 201, start_res.text
    start_data = start_res.json()
    assert start_data["step"] == "verify_email"
    assert "dev_otp" not in start_data
    assert secret_key not in start_res.text

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req["method"] == "POST"
    assert req["url"] == BREVO_OFFICIAL_ENDPOINT
    assert req["headers"]["api-key"] == secret_key
    assert req["headers"]["content-type"] == "application/json"
    assert req["headers"]["accept"] == "application/json"

    payload = req["json"]
    assert payload["sender"] == {"name": "BraveBank", "email": "verified@bravebank.ng"}
    assert payload["to"] == [{"email": "zainab.usman@example.com"}]
    assert payload["subject"] == "BraveBank — Your Email Verification Code"
    assert "5 minutes" in payload["textContent"]
    assert "do not share" in payload["textContent"].lower() or "never share" in payload["textContent"].lower()
    assert "ignore" in payload["textContent"].lower()
    assert "5 minutes" in payload["htmlContent"]

    code_match = re.search(r"\b(\d{6})\b", payload["textContent"])
    assert code_match is not None
    sent_otp = code_match.group(1)
    assert sent_otp in payload["htmlContent"]
    assert sent_otp not in start_res.text

    # Ensure neither OTP nor Brevo API key leaked into logs
    log_output = caplog.text
    assert sent_otp not in log_output
    assert secret_key not in log_output

    # Verify stored OTP in DB is hashed, never plaintext
    otp_row = db_session.scalar(
        select(OtpRecord).where(OtpRecord.target_email == "zainab.usman@example.com")
    )
    assert otp_row is not None
    assert otp_row.code_hash != sent_otp
    assert sent_otp not in otp_row.code_hash

    # 2. Complete email verification & PIN setup
    verify_res = client.post(
        "/api/auth/register/verify-email",
        json={"email": "zainab.usman@example.com", "code": sent_otp},
    )
    assert verify_res.status_code == 200, verify_res.text
    pin_res = client.post(
        "/api/auth/register/set-pin",
        json={
            "registration_token": verify_res.json()["registration_token"],
            "pin": "4321",
            "confirm_pin": "4321",
        },
    )
    assert pin_res.status_code == 201, pin_res.text
    assert pin_res.json()["user"]["email_verified"] is True

    # 3. Password reset via Brevo email OTP
    reset_req = client.post(
        "/api/auth/password/reset-request",
        json={"phone_number": "08044445555"},
    )
    assert reset_req.status_code == 200, reset_req.text
    assert "dev_otp" not in reset_req.json()
    assert len(captured_requests) == 2

    reset_payload = captured_requests[1]["json"]
    assert reset_payload["to"] == [{"email": "zainab.usman@example.com"}]
    assert "password reset" in reset_payload["subject"].lower()
    reset_otp_match = re.search(r"\b(\d{6})\b", reset_payload["textContent"])
    assert reset_otp_match is not None
    reset_otp = reset_otp_match.group(1)
    assert reset_otp not in reset_req.text
    assert reset_otp not in caplog.text
    assert secret_key not in caplog.text

    confirm_res = client.post(
        "/api/auth/password/reset-confirm",
        json={
            "phone_number": "08044445555",
            "otp_code": reset_otp,
            "new_password": "NewBravePassword#2",
            "confirm_password": "NewBravePassword#2",
        },
    )
    assert confirm_res.status_code == 200, confirm_res.text

    # Old password rejected, new password succeeds
    assert (
        client.post(
            "/api/auth/login",
            json={"phone_number": "08044445555", "password": "BravePassword#1"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"phone_number": "08044445555", "password": "NewBravePassword#2"},
        ).status_code
        == 200
    )


def test_brevo_email_link_verification_flow(client, monkeypatch):
    _configure_brevo_env(monkeypatch)
    sent_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"messageId": "<20261126.link@smtp-relay.mailin.fr>"})

    _mock_httpx_client(monkeypatch, handler)

    # Register user first
    reg = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Emeka",
            "surname": "Obi",
            "phone_number": "08033339999",
            "email": "emeka1@example.com",
            "password": "StrongPass#1",
            "confirm_password": "StrongPass#1",
        },
    )
    assert reg.status_code == 201
    otp1 = re.search(r"\b(\d{6})\b", sent_payloads[-1]["textContent"]).group(1)
    ver1 = client.post(
        "/api/auth/register/verify-email",
        json={"email": "emeka1@example.com", "code": otp1},
    )
    auth = client.post(
        "/api/auth/register/set-pin",
        json={
            "registration_token": ver1.json()["registration_token"],
            "pin": "5678",
            "confirm_pin": "5678",
        },
    ).json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    # Link updated email via Brevo
    link = client.post(
        "/api/auth/email/link",
        json={"email": "emeka.updated@example.com"},
        headers=headers,
    )
    assert link.status_code == 200, link.text
    assert "dev_otp" not in link.json()
    assert sent_payloads[-1]["to"] == [{"email": "emeka.updated@example.com"}]
    otp2 = re.search(r"\b(\d{6})\b", sent_payloads[-1]["textContent"]).group(1)

    verify_link = client.post(
        "/api/auth/email/verify",
        json={"otp_code": otp2},
        headers=headers,
    )
    assert verify_link.status_code == 200
    assert verify_link.json()["email"] == "emeka.updated@example.com"


@pytest.mark.parametrize(
    ("api_key", "from_address", "expected_fragment"),
    [
        ("", "no-reply@bravebank.ng", "not configured"),
        ("xkeysib-valid-key", "", "email_from_address"),
        ("xkeysib-valid-key", "not-an-email", "invalid email configuration"),
    ],
)
def test_brevo_missing_or_invalid_configuration_fails_and_rolls_back(
    client, db_session, monkeypatch, api_key, from_address, expected_fragment
):
    _configure_brevo_env(monkeypatch, api_key=api_key, from_address=from_address)

    def should_not_be_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP call must not be attempted when config is invalid")

    _mock_httpx_client(monkeypatch, should_not_be_called)

    res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Config",
            "surname": "Check",
            "phone_number": "08011110000",
            "email": "configcheck@example.com",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    )
    assert res.status_code == 503
    assert expected_fragment in res.json()["detail"].lower()
    # Transaction rolled back cleanly (no pending user or OTP persisted on provider failure)
    assert db_session.scalar(select(func.count(User.id))) == 0
    assert db_session.scalar(select(func.count(OtpRecord.id))) == 0


@pytest.mark.parametrize(
    ("status_code", "brevo_body", "expected_detail_word"),
    [
        (401, {"code": "unauthorized", "message": "Key not found"}, "authentication"),
        (402, {"code": "not_enough_credits", "message": "Insufficient credits"}, "quota"),
        (403, {"code": "permission_denied", "message": "Sender not verified"}, "authorized"),
        (400, {"code": "invalid_parameter", "message": "Invalid sender"}, "rejected"),
        (422, {"code": "invalid_parameter", "message": "Unprocessable payload"}, "rejected"),
        (429, {"code": "too_many_requests", "message": "Rate limit exceeded"}, "rate-limited"),
        (500, {"code": "internal_error", "message": "Server error"}, "unavailable"),
        (503, {"code": "service_unavailable", "message": "Downstream error"}, "unavailable"),
        (201, {"unexpected": "missing_message_id"}, "unexpected response"),
    ],
)
def test_brevo_http_error_and_malformed_responses_handled_safely(
    client, db_session, monkeypatch, caplog, status_code, brevo_body, expected_detail_word
):
    secret_key = "xkeysib-secret-key-redaction-check"
    _configure_brevo_env(monkeypatch, api_key=secret_key)
    caplog.set_level(logging.INFO)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=brevo_body)

    _mock_httpx_client(monkeypatch, handler)

    res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Error",
            "surname": "Case",
            "phone_number": "08022221111",
            "email": "errorcase@example.com",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    )
    assert res.status_code == 503
    detail = res.json()["detail"].lower()
    assert expected_detail_word in detail
    assert secret_key not in res.text
    assert secret_key not in caplog.text
    # Ensure failed provider send did not persist misleading user/OTP rows
    assert db_session.scalar(select(func.count(User.id))) == 0
    assert db_session.scalar(select(func.count(OtpRecord.id))) == 0


def test_brevo_malformed_non_json_response(client, monkeypatch):
    _configure_brevo_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    _mock_httpx_client(monkeypatch, handler)

    res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Bad",
            "surname": "Json",
            "phone_number": "08022223333",
            "email": "badjson@example.com",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    )
    assert res.status_code == 503
    assert "unexpected response" in res.json()["detail"].lower()


@pytest.mark.parametrize(
    ("exc_factory", "expected_fragment"),
    [
        (lambda req: httpx.ConnectError("TLS connection failed", request=req), "unable to connect"),
        (lambda req: httpx.ReadTimeout("Timed out reading response", request=req), "timed out"),
    ],
)
def test_brevo_network_exception_and_timeout_handled_safely(
    client, db_session, monkeypatch, caplog, exc_factory, expected_fragment
):
    secret_key = "xkeysib-network-secret-test"
    _configure_brevo_env(monkeypatch, api_key=secret_key)
    caplog.set_level(logging.INFO)

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc_factory(request)

    _mock_httpx_client(monkeypatch, handler)

    res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Net",
            "surname": "Fail",
            "phone_number": "08022224444",
            "email": "netfail@example.com",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    )
    assert res.status_code == 503
    assert expected_fragment in res.json()["detail"].lower()
    assert secret_key not in res.text
    assert secret_key not in caplog.text
    assert db_session.scalar(select(func.count(User.id))) == 0
    assert db_session.scalar(select(func.count(OtpRecord.id))) == 0


def test_no_smtp_imports_no_frontend_secrets_and_no_dev_otp_fallback():
    backend_files = list(Path("backend/app").rglob("*.py"))
    for py_file in backend_files:
        text = py_file.read_text(encoding="utf-8")
        assert "smtplib" not in text, f"Found smtplib in {py_file}"
        assert "SMTP_SSL" not in text, f"Found SMTP_SSL in {py_file}"

    frontend_files = [
        Path("frontend/index.html"),
        *list(Path("frontend/js").glob("*.js")),
    ]
    for fe_file in frontend_files:
        content = fe_file.read_text(encoding="utf-8")
        assert "BREVO_API_KEY" not in content, f"Found BREVO_API_KEY in {fe_file}"
        assert "api.brevo.com" not in content, f"Found direct Brevo URL in {fe_file}"
        assert "dev_otp" not in content, f"Found dev_otp display fallback in {fe_file}"
        assert "dev-otp-box" not in content or "tr-external-notice" in content


def test_brevo_invalid_recipient_and_non_https_endpoint_rejected(monkeypatch):
    _configure_brevo_env(monkeypatch)

    def should_not_be_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP call must not execute for invalid recipient or URL")

    _mock_httpx_client(monkeypatch, should_not_be_called)

    with pytest.raises(EmailDeliveryError, match="Invalid email configuration"):
        send_otp_email("not-a-valid-email", "123456", "email_registration", 300)

    monkeypatch.setenv("BREVO_API_URL", "http://api.brevo.com/v3/smtp/email")
    get_settings.cache_clear()
    with pytest.raises(EmailDeliveryError, match="Secure HTTPS transport"):
        send_otp_email("customer@example.com", "123456", "email_registration", 300)


def test_brevo_message_id_returned_and_xkeysib_pattern_redacted(monkeypatch, caplog):
    _configure_brevo_env(monkeypatch, api_key="xkeysib-my-live-key-9999")
    caplog.set_level(logging.INFO)

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"messageId": "<msg-123@smtp-relay.mailin.fr>"})

    _mock_httpx_client(monkeypatch, ok_handler)
    msg_id = send_otp_email("user@example.com", "654321", "email_registration", 300)
    assert msg_id == "<msg-123@smtp-relay.mailin.fr>"
    assert "accepted" in caplog.text.lower()
    assert "654321" not in caplog.text
    assert "xkeysib-my-live-key-9999" not in caplog.text

    caplog.clear()

    def err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failure using xkeysib-other-secret-leak", request=request)

    _mock_httpx_client(monkeypatch, err_handler)
    with pytest.raises(EmailDeliveryError):
        send_otp_email("user@example.com", "654321", "email_registration", 300)
    assert "xkeysib-other-secret-leak" not in caplog.text


def test_pending_registration_email_switch_invalidates_prior_otp_and_blocks_incomplete_reset(
    client, db_session, monkeypatch
):
    _configure_brevo_env(monkeypatch)
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"messageId": f"<msg-{len(sent)}>"})

    _mock_httpx_client(monkeypatch, handler)

    r1 = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Bola",
            "surname": "Tinubu",
            "phone_number": "08066667777",
            "email": "bola.first@example.com",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    )
    assert r1.status_code == 201
    assert "delivered" not in r1.json()["message"].lower()
    first_code = re.search(r"\b(\d{6})\b", sent[-1]["textContent"]).group(1)

    # Incomplete registrant cannot abuse password reset before completing registration
    incomplete_reset = client.post(
        "/api/auth/password/reset-request",
        json={"phone_number": "08066667777"},
    )
    assert incomplete_reset.status_code == 400

    # Retrying with same phone and a new email invalidates the previous email's OTP
    r2 = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Bola",
            "surname": "Tinubu",
            "phone_number": "08066667777",
            "email": "bola.second@example.com",
            "password": "Password#123",
            "confirm_password": "Password#123",
        },
    )
    assert r2.status_code == 201
    old_otp = db_session.scalar(
        select(OtpRecord).where(OtpRecord.target_email == "bola.first@example.com")
    )
    assert old_otp is not None and old_otp.invalidated_at is not None

    # Old email OTP is rejected even if submitted against new email
    bad_verify = client.post(
        "/api/auth/register/verify-email",
        json={"email": "bola.second@example.com", "code": first_code},
    )
    assert bad_verify.status_code == 400


def test_password_reset_brevo_cooldown_expiry_and_failure_rollback(client, db_session, monkeypatch):
    _configure_brevo_env(monkeypatch)
    sent: list[dict] = []
    fail_mode = {"active": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if fail_mode["active"]:
            return httpx.Response(500, json={"code": "internal_error", "message": "Brevo down"})
        sent.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"messageId": f"<reset-{len(sent)}>"})

    _mock_httpx_client(monkeypatch, handler)

    # Register and complete account
    s = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Nnamdi",
            "surname": "Azikiwe",
            "phone_number": "08055559999",
            "email": "nnamdi@example.com",
            "password": "OldPassword#1",
            "confirm_password": "OldPassword#1",
        },
    )
    assert s.status_code == 201
    reg_code = re.search(r"\b(\d{6})\b", sent[-1]["textContent"]).group(1)
    v = client.post("/api/auth/register/verify-email", json={"email": "nnamdi@example.com", "code": reg_code})
    p = client.post(
        "/api/auth/register/set-pin",
        json={"registration_token": v.json()["registration_token"], "pin": "1122", "confirm_pin": "1122"},
    )
    assert p.status_code == 201

    # Provider failure on password reset rolls back cleanly (0 password_reset OTP rows stored)
    fail_mode["active"] = True
    failed_req = client.post("/api/auth/password/reset-request", json={"phone_number": "08055559999"})
    assert failed_req.status_code == 503
    assert (
        db_session.scalar(
            select(func.count(OtpRecord.id)).where(OtpRecord.purpose == "password_reset")
        )
        == 0
    )

    # Succeeds when Brevo recovers, enforces 60s cooldown, and rejects expired codes
    fail_mode["active"] = False
    ok_req = client.post("/api/auth/password/reset-request", json={"phone_number": "08055559999"})
    assert ok_req.status_code == 200
    assert "delivered" not in ok_req.json()["message"].lower()
    reset_code = re.search(r"\b(\d{6})\b", sent[-1]["textContent"]).group(1)

    cooldown_req = client.post("/api/auth/password/reset-request", json={"phone_number": "08055559999"})
    assert cooldown_req.status_code == 429

    # Expire the reset OTP and verify rejection
    reset_row = db_session.scalar(
        select(OtpRecord)
        .where(OtpRecord.purpose == "password_reset", OtpRecord.invalidated_at.is_(None))
        .order_by(desc(OtpRecord.created_at))
    )
    reset_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    expired_confirm = client.post(
        "/api/auth/password/reset-confirm",
        json={
            "phone_number": "08055559999",
            "otp_code": reset_code,
            "new_password": "NewPassword#2",
            "confirm_password": "NewPassword#2",
        },
    )
    assert expired_confirm.status_code == 400
    assert "expired" in expired_confirm.json()["detail"].lower()


def _register_user_with_brevo(client, sent_requests: list[dict], phone: str, email: str, pin: str = "2468") -> dict:
    start = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Adaeze",
            "surname": "Nwosu",
            "phone_number": phone,
            "email": email,
            "password": "BravePassword#1",
            "confirm_password": "BravePassword#1",
        },
    )
    assert start.status_code == 201, start.text
    last = sent_requests[-1]
    body = last["json"] if "json" in last else last
    reg_otp = re.search(r"\b(\d{6})\b", body["textContent"]).group(1)
    ver = client.post(
        "/api/auth/register/verify-email",
        json={"email": email.lower(), "code": reg_otp},
    )
    assert ver.status_code == 200, ver.text
    pin_res = client.post(
        "/api/auth/register/set-pin",
        json={"registration_token": ver.json()["registration_token"], "pin": pin, "confirm_pin": pin},
    )
    assert pin_res.status_code == 201, pin_res.text
    auth = pin_res.json()
    client.cookies.clear()
    return {
        "user": auth["user"],
        "headers": {"Authorization": f"Bearer {auth['access_token']}"},
    }


def test_pin_reset_brevo_success_and_argon2_update(client, db_session, monkeypatch, caplog):
    secret_key = "xkeysib-pin-reset-secret-123"
    _configure_brevo_env(monkeypatch, api_key=secret_key)
    caplog.set_level(logging.DEBUG)
    sent_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "json": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(201, json={"messageId": f"<pin-{len(sent_requests)}@smtp-relay.mailin.fr>"})

    _mock_httpx_client(monkeypatch, handler)

    customer = _register_user_with_brevo(
        client,
        sent_requests,
        phone="08091112222",
        email="Adaeze.Nwosu@example.com",
        pin="1234",
    )
    assert customer["user"]["email_verified"] is True
    assert len(sent_requests) == 1

    # Fund account so we can prove old PIN fails and new PIN authorizes transactions
    dep = client.post("/api/accounts/deposit", json={"amount": "5000.00"}, headers=customer["headers"])
    assert dep.status_code == 201

    caplog.clear()
    reset_req = client.post("/api/auth/pin/reset-request", headers=customer["headers"])
    assert reset_req.status_code == 200, reset_req.text
    req_data = reset_req.json()
    assert req_data["masked_email"] == "ad***u@example.com"
    assert req_data["otp_expires_in_seconds"] == 300
    assert req_data["resend_cooldown_seconds"] == 60
    assert "dev_otp" not in req_data
    assert secret_key not in reset_req.text

    assert len(sent_requests) == 2
    brevo_call = sent_requests[-1]
    assert brevo_call["method"] == "POST"
    assert brevo_call["url"] == BREVO_OFFICIAL_ENDPOINT
    assert brevo_call["headers"]["api-key"] == secret_key
    payload = brevo_call["json"]
    assert payload["to"] == [{"email": "adaeze.nwosu@example.com"}]
    assert "transaction pin reset" in payload["subject"].lower()
    assert "5 minutes" in payload["textContent"]
    assert "5 minutes" in payload["htmlContent"]

    otp_match = re.search(r"\b(\d{6})\b", payload["textContent"])
    assert otp_match is not None
    pin_otp = otp_match.group(1)
    assert pin_otp in payload["htmlContent"]
    assert pin_otp not in reset_req.text
    assert pin_otp not in caplog.text
    assert secret_key not in caplog.text

    otp_row = db_session.scalar(
        select(OtpRecord)
        .where(
            OtpRecord.target_email == "adaeze.nwosu@example.com",
            OtpRecord.purpose == "pin_reset",
            OtpRecord.invalidated_at.is_(None),
        )
        .order_by(desc(OtpRecord.created_at))
    )
    assert otp_row is not None
    assert otp_row.code_hash != pin_otp
    assert pin_otp not in otp_row.code_hash
    assert 290 <= (otp_row.expires_at - otp_row.created_at).total_seconds() <= 305

    confirm = client.post(
        "/api/auth/pin/reset-confirm",
        json={"otp_code": pin_otp, "new_pin": "9876", "confirm_pin": "9876"},
        headers=customer["headers"],
    )
    assert confirm.status_code == 200, confirm.text
    assert "dev_otp" not in confirm.json()

    pin_row = db_session.scalar(
        select(TransactionPin).where(TransactionPin.user_id == customer["user"]["id"])
    )
    assert pin_row is not None
    assert pin_row.pin_hash.startswith("$argon2")

    old_wdr = client.post(
        "/api/accounts/withdraw",
        json={"amount": "500.00", "pin": "1234"},
        headers=customer["headers"],
    )
    assert old_wdr.status_code == 401

    new_wdr = client.post(
        "/api/accounts/withdraw",
        json={"amount": "500.00", "pin": "9876"},
        headers=customer["headers"],
    )
    assert new_wdr.status_code == 201


def test_pin_reset_requires_verified_email_and_rolls_back_on_brevo_failure(
    client, db_session, monkeypatch
):
    _configure_brevo_env(monkeypatch)
    sent_payloads: list[dict] = []
    fail_mode = {"active": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if fail_mode["active"]:
            return httpx.Response(500, json={"code": "internal_error", "message": "Brevo down"})
        sent_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"messageId": f"<pin-err-{len(sent_payloads)}>"})

    _mock_httpx_client(monkeypatch, handler)

    # Register user
    start = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Kelechi",
            "surname": "Iheanacho",
            "phone_number": "08092223333",
            "email": "kelechi@example.com",
            "password": "BravePassword#1",
            "confirm_password": "BravePassword#1",
        },
    )
    assert start.status_code == 201
    reg_otp = re.search(r"\b(\d{6})\b", sent_payloads[-1]["textContent"]).group(1)
    ver = client.post("/api/auth/register/verify-email", json={"email": "kelechi@example.com", "code": reg_otp})
    pin_res = client.post(
        "/api/auth/register/set-pin",
        json={"registration_token": ver.json()["registration_token"], "pin": "2244", "confirm_pin": "2244"},
    )
    assert pin_res.status_code == 201
    headers = {"Authorization": f"Bearer {pin_res.json()['access_token']}"}
    user_id = pin_res.json()["user"]["id"]
    client.cookies.clear()

    # 1. Brevo failure returns 503 and rolls back cleanly (0 pin_reset OTP rows)
    fail_mode["active"] = True
    failed_req = client.post("/api/auth/pin/reset-request", headers=headers)
    assert failed_req.status_code == 503
    assert (
        db_session.scalar(
            select(func.count(OtpRecord.id)).where(OtpRecord.purpose == "pin_reset")
        )
        == 0
    )

    # 2. Missing BREVO_API_KEY also fails cleanly with rollback
    _configure_brevo_env(monkeypatch, api_key="")
    fail_mode["active"] = False
    unconfigured_req = client.post("/api/auth/pin/reset-request", headers=headers)
    assert unconfigured_req.status_code == 503
    assert (
        db_session.scalar(
            select(func.count(OtpRecord.id)).where(OtpRecord.purpose == "pin_reset")
        )
        == 0
    )
    _configure_brevo_env(monkeypatch)

    # 3. Unverified email is rejected on both reset-request and reset-confirm
    user_row = db_session.get(User, user_id)
    user_row.email_verified = False
    db_session.commit()

    calls_before = len(sent_payloads)
    unverified_req = client.post("/api/auth/pin/reset-request", headers=headers)
    assert unverified_req.status_code == 400
    assert "verified email" in unverified_req.json()["detail"].lower()
    assert len(sent_payloads) == calls_before

    unverified_confirm = client.post(
        "/api/auth/pin/reset-confirm",
        json={"otp_code": "123456", "new_pin": "5566", "confirm_pin": "5566"},
        headers=headers,
    )
    assert unverified_confirm.status_code == 400
    assert "verified email" in unverified_confirm.json()["detail"].lower()


def test_pin_reset_otp_cooldown_invalidation_expiry_and_max_attempts(client, db_session, monkeypatch):
    _configure_brevo_env(monkeypatch)
    sent_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"messageId": f"<pin-sec-{len(sent_payloads)}>"})

    _mock_httpx_client(monkeypatch, handler)

    start = client.post(
        "/api/auth/register/start",
        json={
            "first_name": "Tunde",
            "surname": "Bakare",
            "phone_number": "08093334444",
            "email": "tunde.bakare@example.com",
            "password": "BravePassword#1",
            "confirm_password": "BravePassword#1",
        },
    )
    assert start.status_code == 201
    reg_otp = re.search(r"\b(\d{6})\b", sent_payloads[-1]["textContent"]).group(1)
    ver = client.post("/api/auth/register/verify-email", json={"email": "tunde.bakare@example.com", "code": reg_otp})
    pin_res = client.post(
        "/api/auth/register/set-pin",
        json={"registration_token": ver.json()["registration_token"], "pin": "1357", "confirm_pin": "1357"},
    )
    assert pin_res.status_code == 201
    headers = {"Authorization": f"Bearer {pin_res.json()['access_token']}"}
    client.cookies.clear()

    # 1. Request first PIN reset OTP & verify 60s resend cooldown
    req1 = client.post("/api/auth/pin/reset-request", headers=headers)
    assert req1.status_code == 200
    otp1 = re.search(r"\b(\d{6})\b", sent_payloads[-1]["textContent"]).group(1)

    cooldown_req = client.post("/api/auth/pin/reset-request", headers=headers)
    assert cooldown_req.status_code == 429

    # 2. Age last_sent_at past 60s -> resend succeeds and invalidates first OTP
    row1 = db_session.scalar(
        select(OtpRecord)
        .where(OtpRecord.purpose == "pin_reset", OtpRecord.invalidated_at.is_(None))
        .order_by(desc(OtpRecord.created_at))
    )
    row1.last_sent_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    db_session.commit()

    req2 = client.post("/api/auth/pin/reset-request", headers=headers)
    assert req2.status_code == 200
    otp2 = re.search(r"\b(\d{6})\b", sent_payloads[-1]["textContent"]).group(1)

    db_session.refresh(row1)
    assert row1.invalidated_at is not None

    stale_confirm = client.post(
        "/api/auth/pin/reset-confirm",
        json={"otp_code": otp1, "new_pin": "9999", "confirm_pin": "9999"},
        headers=headers,
    )
    if otp1 != otp2:
        assert stale_confirm.status_code == 400
        assert "4 attempt(s) remaining" in stale_confirm.json()["detail"]
        start_attempt = 2
    else:
        start_attempt = 1

    # 3. Invalid OTP decrements attempts and max 5 failures invalidate OTP2
    wrong_otp = "000000" if otp2 != "000000" else "999999"
    for attempt_idx in range(start_attempt, 6):
        bad = client.post(
            "/api/auth/pin/reset-confirm",
            json={"otp_code": wrong_otp, "new_pin": "8888", "confirm_pin": "8888"},
            headers=headers,
        )
        assert bad.status_code == 400
        expected_remaining = 5 - attempt_idx
        assert f"{expected_remaining} attempt(s) remaining" in bad.json()["detail"]

    # Even the real otp2 is now rejected because 5 failed attempts invalidated it
    blocked_real = client.post(
        "/api/auth/pin/reset-confirm",
        json={"otp_code": otp2, "new_pin": "8888", "confirm_pin": "8888"},
        headers=headers,
    )
    assert blocked_real.status_code == 400

    # 4. Request fresh OTP3, expire it past 5 minutes, and verify rejection
    req3 = client.post("/api/auth/pin/reset-request", headers=headers)
    assert req3.status_code == 200
    otp3 = re.search(r"\b(\d{6})\b", sent_payloads[-1]["textContent"]).group(1)
    row3 = db_session.scalar(
        select(OtpRecord)
        .where(OtpRecord.purpose == "pin_reset", OtpRecord.invalidated_at.is_(None))
        .order_by(desc(OtpRecord.created_at))
    )
    row3.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    expired = client.post(
        "/api/auth/pin/reset-confirm",
        json={"otp_code": otp3, "new_pin": "7777", "confirm_pin": "7777"},
        headers=headers,
    )
    assert expired.status_code == 400
    assert "expired" in expired.json()["detail"].lower()

    # Original PIN "1357" was never changed during all failed attempts
    client.post("/api/accounts/deposit", json={"amount": "2000.00"}, headers=headers)
    still_original = client.post(
        "/api/accounts/withdraw",
        json={"amount": "100.00", "pin": "1357"},
        headers=headers,
    )
    assert still_original.status_code == 201

