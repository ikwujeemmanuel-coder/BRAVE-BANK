/** Customer Profile, Security & PIN Settings, Active Sessions, and 24/7 Support screens. */

import { apiRequest } from "./api.js";
import { isSoundMuted, toggleSoundMuted } from "./effects.js";
import { icon } from "./icons.js";
import { appState, escapeHtml, formatDateTime } from "./state.js";
import { showToast } from "./ui.js";

export async function renderProfile(root, navigate, refreshUser, onLogout) {
  const me = await apiRequest("/api/auth/me");
  appState.user = me;
  refreshUser();

  const initials = `${me.first_name[0] || "B"}${me.surname[0] || "B"}`.toUpperCase();
  const statusBadge = me.email_verified
    ? "Email Verified"
    : me.phone_verified
      ? "Phone Verified"
      : "Verification Pending";

  root.innerHTML = `
    <div class="grid-2">
      <section class="card form-stack">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <button type="button" class="back-arrow-btn" id="prof-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
          <span class="status-tag verified">${escapeHtml(statusBadge)}</span>
        </div>

        <div style="text-align:center;">
          <div class="avatar-chip" style="width:70px; height:70px; font-size:1.4rem; margin:0 auto 10px;">
            ${escapeHtml(initials)}
          </div>
          <h3 style="margin:0; font-size:1.25rem;">${escapeHtml(me.first_name)} ${escapeHtml(me.surname)}</h3>
          <small style="color:var(--muted);">BraveBank NGN Customer</small>
        </div>

        <div class="summary-blue-card">
          <div class="summary-kv-row">
            <span class="summary-kv-left">Phone Number</span>
            <strong class="summary-kv-val">${escapeHtml(me.phone_number)} (${me.phone_verified ? "Verified" : "Unverified"})</strong>
          </div>
          <div class="summary-kv-row">
            <span class="summary-kv-left">Account Number</span>
            <strong class="summary-kv-val">${escapeHtml(me.account_number || "—")}</strong>
          </div>
          <div class="summary-kv-row">
            <span class="summary-kv-left">Email Address</span>
            <strong class="summary-kv-val">${me.email ? `${escapeHtml(me.email)} (${me.email_verified ? "Verified" : "Pending"})` : "Not linked"}</strong>
          </div>
          <div class="summary-kv-row">
            <span class="summary-kv-left">Member Since</span>
            <strong class="summary-kv-val">${escapeHtml(formatDateTime(me.created_at))}</strong>
          </div>
        </div>

        <div class="grid-2 compact-grid">
          <button id="prof-acct-btn" type="button" class="btn btn-outline-blue btn-pill">Account Details</button>
          <button id="prof-sec-btn" type="button" class="btn btn-primary btn-pill">Security &amp; PIN</button>
        </div>

        <button id="prof-support-btn" type="button" class="option-row">
          <span style="display:flex; align-items:center; gap:10px;">${icon("helpCircle", 18)} <strong>24/7 Support &amp; FAQs</strong></span>
          ${icon("chevronRight", 18)}
        </button>

        <button id="prof-logout-btn" type="button" class="btn btn-danger btn-pill btn-full">
          ${icon("logOut", 17)}
          <span>Logout</span>
        </button>
      </section>

      <section class="card form-stack">
        <h3>Update &amp; Verify Email</h3>
        <p class="muted-copy">Manage the verified email address associated with your BraveBank account.</p>
        <form id="link-email-form" class="form-stack">
          <label class="field">
            <span>Email Address</span>
            <div style="display:flex; gap:8px;">
              <input id="link-email-input" type="email" required value="${escapeHtml(me.email || "")}" placeholder="you@example.com" />
              <button type="submit" class="btn btn-outline-blue">Update</button>
            </div>
          </label>
        </form>
        <div id="email-dev-otp" class="dev-otp-box hidden"></div>
        <form id="verify-email-form" class="form-stack ${me.email && !me.email_verified ? "" : "hidden"}">
          <label class="field">
            <span>6-Digit Email Verification Code</span>
            <div style="display:flex; gap:8px;">
              <input id="verify-email-code" type="text" maxlength="6" pattern="\\d{6}" required placeholder="123456" />
              <button type="submit" class="btn btn-primary">Verify</button>
            </div>
          </label>
        </form>
      </section>
    </div>
  `;

  document.getElementById("prof-back-btn").addEventListener("click", () => navigate("dashboard"));
  document.getElementById("prof-acct-btn").addEventListener("click", () => navigate("account-details"));
  document.getElementById("prof-sec-btn").addEventListener("click", () => navigate("settings"));
  document.getElementById("prof-support-btn").addEventListener("click", () => navigate("support"));
  document.getElementById("prof-logout-btn").addEventListener("click", onLogout);

  document.getElementById("link-email-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await apiRequest("/api/auth/email/link", {
        method: "POST",
        body: JSON.stringify({ email: document.getElementById("link-email-input").value }),
      });
      showToast(res.message, "success");
      document.getElementById("verify-email-form").classList.remove("hidden");
      if (res.dev_otp) {
        const box = document.getElementById("email-dev-otp");
        box.textContent = `Development Email OTP: ${res.dev_otp}`;
        box.classList.remove("hidden");
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("verify-email-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await apiRequest("/api/auth/email/verify", {
        method: "POST",
        body: JSON.stringify({ otp_code: document.getElementById("verify-email-code").value }),
      });
      showToast("Email verified!", "success");
      await renderProfile(root, navigate, refreshUser, onLogout);
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

export async function renderSettings(root, navigate, refreshUser) {
  const [me, sessions] = await Promise.all([
    apiRequest("/api/auth/me"),
    apiRequest("/api/auth/sessions"),
  ]);
  appState.user = me;
  refreshUser();

  root.innerHTML = `
    <div class="grid-2">
      <section class="card form-stack">
        <div style="display:flex; align-items:center; gap:10px;">
          <button type="button" class="back-arrow-btn" id="sec-back-btn" aria-label="Back to Profile">${icon("arrowLeft", 20)}</button>
          <h3 style="margin:0;">4-Digit Transaction PIN</h3>
        </div>
        <p class="muted-copy" style="font-size:0.82rem;">
          All transfers, withdrawals, savings, and bill payments use a 4-digit PIN. Upgrading from an older 6-digit PIN? Enter your current 6-digit PIN or reset via OTP below.
        </p>
        <form id="pin-form" class="form-stack">
          ${
            me.has_transaction_pin
              ? `
            <label class="field">
              <span>Current PIN (4 digits, or 6 digits if upgrading)</span>
              <input id="pin-current" type="password" inputmode="numeric" minlength="4" maxlength="6" pattern="(\\d{4}|\\d{6})" required placeholder="Current PIN" />
            </label>`
              : ""
          }
          <label class="field">
            <span>${me.has_transaction_pin ? "New 4-Digit PIN" : "Set 4-Digit PIN"}</span>
            <input id="pin-new" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="4 digits" />
          </label>
          <label class="field">
            <span>Confirm 4-Digit PIN</span>
            <input id="pin-confirm" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="Repeat 4 digits" />
          </label>
          <button type="submit" class="btn btn-primary btn-pill">${me.has_transaction_pin ? "Update to 4-Digit PIN" : "Set 4-Digit PIN"}</button>
        </form>

        <div style="border-top:1px solid var(--border); padding-top:12px;">
          <button id="request-pin-reset-btn" type="button" class="btn btn-outline-blue btn-sm">Forgot or Upgrading PIN? Reset via 6-Digit OTP</button>
          <div id="pin-reset-dev-otp" class="dev-otp-box hidden" style="margin-top:10px;"></div>
          <form id="pin-reset-confirm-form" class="form-stack hidden" style="margin-top:10px;">
            <label class="field">
              <span>6-Digit OTP</span>
              <input id="pin-reset-otp" type="text" inputmode="numeric" maxlength="6" pattern="\\d{6}" required placeholder="6-digit OTP" />
            </label>
            <label class="field">
              <span>New 4-Digit PIN</span>
              <input id="pin-reset-new" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="4 digits" />
            </label>
            <label class="field">
              <span>Confirm 4-Digit PIN</span>
              <input id="pin-reset-confirm" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="Repeat 4 digits" />
            </label>
            <button type="submit" class="btn btn-primary btn-sm">Confirm PIN Reset</button>
          </form>
        </div>
      </section>

      <section class="card form-stack">
        <h3>Change Password (7+ chars &amp; symbol)</h3>
        <form id="change-pw-form" class="form-stack">
          <label class="field">
            <span>Current Password</span>
            <input id="pw-current" type="password" required />
          </label>
          <label class="field">
            <span>New Password</span>
            <input id="pw-new" type="password" required minlength="7" />
          </label>
          <label class="field">
            <span>Confirm New Password</span>
            <input id="pw-confirm" type="password" required minlength="7" />
          </label>
          <button type="submit" class="btn btn-outline-blue btn-pill">Update Password</button>
        </form>
      </section>
    </div>

    <section class="card">
      <h3>Active Sessions</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Device / User Agent</th>
              <th>IP</th>
              <th>Created</th>
              <th class="num">Action</th>
            </tr>
          </thead>
          <tbody>
            ${sessions
              .map(
                (s) => `
              <tr>
                <td>${escapeHtml(s.user_agent || "Browser Session")} ${s.is_current ? '<span class="status-tag active">Current</span>' : ""}</td>
                <td>${escapeHtml(s.ip_address || "—")}</td>
                <td>${escapeHtml(formatDateTime(s.created_at))}</td>
                <td class="num">
                  ${
                    s.is_current
                      ? "Active"
                      : `<button type="button" class="btn btn-danger btn-sm" data-revoke-session="${escapeHtml(s.id)}">Revoke</button>`
                  }
                </td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <div class="section-header" style="margin-bottom:6px;">
        <div>
          <h3 style="margin:0;">Audio &amp; Visual Feedback</h3>
          <p class="muted-copy" style="margin-top:4px;">Control the gentle chime played on confirmed internal BraveBank transfers.</p>
        </div>
        <button id="settings-sound-toggle-btn" type="button" class="btn btn-outline-blue btn-pill btn-sm">
          ${isSoundMuted() ? icon("volumeX", 16) : icon("volume2", 16)}
          <span>${isSoundMuted() ? "Sounds Muted" : "Sounds Enabled"}</span>
        </button>
      </div>
    </section>
  `;

  document.getElementById("sec-back-btn").addEventListener("click", () => navigate("profile"));
  const settingsSoundBtn = document.getElementById("settings-sound-toggle-btn");
  if (settingsSoundBtn) {
    settingsSoundBtn.addEventListener("click", () => {
      const muted = toggleSoundMuted();
      settingsSoundBtn.innerHTML = `${muted ? icon("volumeX", 16) : icon("volume2", 16)} <span>${muted ? "Sounds Muted" : "Sounds Enabled"}</span>`;
      showToast(muted ? "Transaction sounds muted." : "Transaction sounds enabled.", "info");
    });
  }

  document.getElementById("pin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const newPin = document.getElementById("pin-new").value.trim();
    const confirmPin = document.getElementById("pin-confirm").value.trim();
    if (!/^\d{4}$/.test(newPin) || newPin !== confirmPin) {
      showToast("New PIN must be exactly 4 numeric digits and match confirmation.", "error");
      return;
    }
    try {
      if (me.has_transaction_pin) {
        await apiRequest("/api/auth/pin/change", {
          method: "POST",
          body: JSON.stringify({
            current_pin: document.getElementById("pin-current").value.trim(),
            new_pin: newPin,
            confirm_pin: confirmPin,
          }),
        });
      } else {
        await apiRequest("/api/auth/pin/set", {
          method: "POST",
          body: JSON.stringify({
            pin: newPin,
            confirm_pin: confirmPin,
          }),
        });
      }
      showToast("4-digit transaction PIN updated.", "success");
      await renderSettings(root, navigate, refreshUser);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("request-pin-reset-btn").addEventListener("click", async () => {
    try {
      const res = await apiRequest("/api/auth/pin/reset-request", { method: "POST" });
      document.getElementById("pin-reset-confirm-form").classList.remove("hidden");
      if (res.dev_otp) {
        const box = document.getElementById("pin-reset-dev-otp");
        box.textContent = `Development PIN Reset OTP: ${res.dev_otp}`;
        box.classList.remove("hidden");
      }
      showToast(res.message, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("pin-reset-confirm-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const newPin = document.getElementById("pin-reset-new").value.trim();
    const confirmPin = document.getElementById("pin-reset-confirm").value.trim();
    if (!/^\d{4}$/.test(newPin) || newPin !== confirmPin) {
      showToast("New PIN must be exactly 4 numeric digits and match confirmation.", "error");
      return;
    }
    try {
      const res = await apiRequest("/api/auth/pin/reset-confirm", {
        method: "POST",
        body: JSON.stringify({
          otp_code: document.getElementById("pin-reset-otp").value.trim(),
          new_pin: newPin,
          confirm_pin: confirmPin,
        }),
      });
      showToast(res.message, "success");
      await renderSettings(root, navigate, refreshUser);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("change-pw-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await apiRequest("/api/auth/password/change", {
        method: "POST",
        body: JSON.stringify({
          current_password: document.getElementById("pw-current").value,
          new_password: document.getElementById("pw-new").value,
          confirm_password: document.getElementById("pw-confirm").value,
        }),
      });
      showToast("Password updated.", "success");
      e.target.reset();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  root.querySelectorAll("[data-revoke-session]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiRequest(`/api/auth/sessions/${btn.dataset.revokeSession}`, { method: "DELETE" });
      showToast("Session revoked.", "success");
      await renderSettings(root, navigate, refreshUser);
    });
  });
}

export async function renderSupport(root, navigate) {
  const [faqs, tickets] = await Promise.all([
    apiRequest("/api/support/faqs"),
    apiRequest("/api/support/tickets"),
  ]);

  root.innerHTML = `
    <div class="grid-2">
      <section class="card form-stack">
        <div style="display:flex; align-items:center; gap:10px;">
          <button type="button" class="back-arrow-btn" id="sup-back-btn" aria-label="Back">${icon("arrowLeft", 20)}</button>
          <h3 style="margin:0;">24/7 Support &amp; FAQs</h3>
        </div>
        <input id="faq-search" type="search" placeholder="Search FAQ..." />
        <div id="faq-list" class="form-stack"></div>
      </section>

      <section class="card form-stack">
        <h3>Message BraveBank Support</h3>
        <form id="ticket-form" class="form-stack">
          <label class="field">
            <span>Category</span>
            <select id="ticket-cat">
              <option value="transfers">Transfers</option>
              <option value="security">Account &amp; Security</option>
              <option value="bills">Bill Payments</option>
              <option value="general">General</option>
            </select>
          </label>
          <label class="field">
            <span>Subject</span>
            <input id="ticket-subj" type="text" required minlength="4" placeholder="Brief summary" />
          </label>
          <label class="field">
            <span>Message</span>
            <textarea id="ticket-msg" rows="3" required minlength="10" placeholder="Describe your request..."></textarea>
          </label>
          <button type="submit" class="btn btn-primary btn-pill">Submit Support Ticket</button>
        </form>
      </section>
    </div>

    <section class="card">
      <h3>Support Ticket History</h3>
      ${
        tickets.length
          ? `
        <div class="form-stack">
          ${tickets
            .map(
              (t) => `
            <div style="border:1px solid var(--border); border-radius:14px; padding:14px;">
              <div class="section-header" style="margin-bottom:6px;">
                <strong>${escapeHtml(t.reference)} &middot; ${escapeHtml(t.subject)}</strong>
                <span class="status-tag ${escapeHtml(t.status)}">${escapeHtml(t.status)}</span>
              </div>
              <p style="margin:0 0 6px; font-size:0.88rem;">${escapeHtml(t.message)}</p>
              <div style="background:var(--bg-light); padding:10px; border-radius:10px; font-size:0.84rem; color:var(--primary-deep);">
                <strong>BraveBank Support:</strong> ${escapeHtml(t.admin_response || "Under review.")}
              </div>
            </div>`
            )
            .join("")}
        </div>`
          : `<div class="empty-state">No support tickets yet.</div>`
      }
    </section>
  `;

  document.getElementById("sup-back-btn").addEventListener("click", () => navigate("profile"));

  function drawFaqs(filterText = "") {
    const q = filterText.trim().toLowerCase();
    const matched = faqs.filter(
      (f) => f.question.toLowerCase().includes(q) || f.answer.toLowerCase().includes(q)
    );
    document.getElementById("faq-list").innerHTML = matched.length
      ? matched
          .map(
            (f) => `
          <div style="border-bottom:1px solid var(--border); padding-bottom:10px;">
            <strong style="font-size:0.9rem;">${escapeHtml(f.question)}</strong>
            <p class="muted-copy" style="margin-top:4px;">${escapeHtml(f.answer)}</p>
          </div>`
          )
          .join("")
      : `<div class="empty-state">No FAQ matched your search.</div>`;
  }

  drawFaqs();
  document.getElementById("faq-search").addEventListener("input", (e) => drawFaqs(e.target.value));

  document.getElementById("ticket-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await apiRequest("/api/support/tickets", {
        method: "POST",
        body: JSON.stringify({
          category: document.getElementById("ticket-cat").value,
          subject: document.getElementById("ticket-subj").value,
          message: document.getElementById("ticket-msg").value,
        }),
      });
      showToast("Support ticket created.", "success");
      await renderSupport(root, navigate);
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}
