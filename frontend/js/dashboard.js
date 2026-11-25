/** Main BraveBank Dashboard and Account Details screens matching the official visual mockup. */

import { apiRequest } from "./api.js";
import { isSoundMuted, toggleSoundMuted } from "./effects.js";
import { icon } from "./icons.js";
import { brandStarSvg } from "./logo.js";
import { appState, escapeHtml, formatNGN } from "./state.js";
import { renderTransactionCards, wireTransactionClicks } from "./transfers.js";
import { showToast } from "./ui.js";

export async function renderDashboard(root, navigate, refreshChrome) {
  const dash = await apiRequest("/api/accounts/dashboard");
  appState.dashboard = dash;
  refreshChrome(dash.unread_notifications);

  const firstName = appState.user?.first_name || "Customer";
  const unread = Number(dash.unread_notifications || 0);
  const maxDayVal = Math.max(
    1,
    ...(dash.weekly_activity || []).flatMap((d) => [Number(d.inflow), Number(d.outflow)])
  );

  root.innerHTML = `
    <!-- Greeting Header matching Mockup Right Screen -->
    <header class="dash-greeting-bar">
      <div>
        <h2 class="dash-hello">Hello, ${escapeHtml(firstName)}!</h2>
        <p class="dash-welcome-sub">Welcome back to BraveBank</p>
      </div>
      <div class="dash-header-icons">
        <button id="dash-sound-btn" type="button" class="circle-icon-btn ${isSoundMuted() ? "is-muted" : ""}" aria-label="${isSoundMuted() ? "Unmute transaction sounds" : "Mute transaction sounds"}" title="${isSoundMuted() ? "Sounds Muted" : "Sounds On"}">
          ${isSoundMuted() ? icon("volumeX", 18) : icon("volume2", 18)}
        </button>
        <button id="dash-notif-btn" type="button" class="circle-icon-btn notif-btn" aria-label="Notifications">
          ${icon("bell", 19)}
          ${unread > 0 ? `<span class="notif-count-pill">${unread > 99 ? "99+" : unread}</span>` : ""}
        </button>
        <button id="dash-profile-btn" type="button" class="circle-icon-btn dash-avatar-circle" aria-label="Profile">
          ${icon("user", 19)}
        </button>
      </div>
    </header>

    <!-- Royal Blue Account Balance Card -->
    <section class="balance-hero-card">
      <div class="balance-card-watermark" aria-hidden="true">${brandStarSvg("splash", "balance-card-star")}</div>
      <div class="balance-card-top">
        <div class="balance-label-row">
          <span>Account Balance</span>
          <button id="copy-acct-btn" type="button" class="acct-chip-copy" title="Copy account number">
            <span>${escapeHtml(dash.account.account_number)}</span>
            ${icon("copy", 12)}
          </button>
        </div>
        <button id="toggle-balance-btn" type="button" class="eye-inline-btn" aria-label="${appState.hideBalance ? "Show balance" : "Hide balance"}">
          ${appState.hideBalance ? icon("eyeOff", 16) : icon("eye", 16)}
        </button>
      </div>

      <div id="dash-balance-text" class="hero-balance-figure">
        ${appState.hideBalance ? "&#8358; ••••••••" : formatNGN(dash.account.available_balance)}
      </div>
      <div style="font-size:0.74rem; color:rgba(255,255,255,0.86); font-weight:600; margin-top:4px; position:relative; z-index:1;">
        Demo Account &middot; Simulated Funds
      </div>

      <div class="hero-add-money-wrap">
        <button id="hero-add-money-btn" type="button" class="hero-add-money-btn">
          ${icon("wallet", 15)}
          <span>Add Money</span>
        </button>
      </div>
    </section>

    <!-- 4x2 Quick Action Grid -->
    <section class="quick-action-grid-8" aria-label="Quick Actions">
      <button id="qa-transfer" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("send", 20)}</span>
        <span>Transfer</span>
      </button>
      <button id="qa-add-money" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("plusCircle", 20)}</span>
        <span>Add Money</span>
      </button>
      <button id="qa-withdraw" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("wallet", 20)}</span>
        <span>Withdraw</span>
      </button>
      <button id="qa-airtime" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("smartphone", 20)}</span>
        <span>Airtime</span>
      </button>
      <button id="qa-data" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("globe", 20)}</span>
        <span>Data</span>
      </button>
      <button id="qa-electricity" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("zap", 20)}</span>
        <span>Electricity</span>
      </button>
      <button id="qa-tv" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("tv", 20)}</span>
        <span>TV</span>
      </button>
      <button id="qa-savings" type="button" class="qa-card-tile">
        <span class="qa-icon-badge">${icon("piggyBank", 20)}</span>
        <span>Savings</span>
      </button>
    </section>

    <!-- Recent Transactions -->
    <section class="card">
      <div class="section-header">
        <h3>Recent Transactions</h3>
        <button id="dash-history-btn" type="button" class="btn-link" style="display:inline-flex; align-items:center; gap:3px;">
          <span>See All</span>
          ${icon("chevronRight", 15)}
        </button>
      </div>
      ${renderTransactionCards(dash.recent_transactions)}
    </section>

    <!-- Weekly Activity & Savings Overview -->
    <section class="grid-2">
      <div class="card">
        <div class="section-header">
          <h3>Weekly Activity</h3>
          <small style="color:var(--muted);">7-day NGN flow</small>
        </div>
        <div class="grid-2 compact-grid" style="margin-bottom:8px;">
          <div>
            <small style="color:var(--muted);">Total Received</small>
            <div class="credit" style="font-weight:800;">${formatNGN(dash.total_received)}</div>
          </div>
          <div>
            <small style="color:var(--muted);">Total Sent</small>
            <div class="debit" style="font-weight:800;">${formatNGN(dash.total_sent)}</div>
          </div>
        </div>
        <div class="weekly-bars">
          ${(dash.weekly_activity || [])
            .map((d) => {
              const inH = Math.max(4, Math.round((Number(d.inflow) / maxDayVal) * 78));
              const outH = Math.max(4, Math.round((Number(d.outflow) / maxDayVal) * 78));
              return `
                <div class="bar-col" title="${escapeHtml(d.date)}: +${formatNGN(d.inflow)} / -${formatNGN(d.outflow)}">
                  <div class="bar-pair">
                    <div class="bar-in" style="height:${inH}px"></div>
                    <div class="bar-out" style="height:${outH}px"></div>
                  </div>
                  <span class="bar-label">${escapeHtml(d.day)}</span>
                </div>`;
            })
            .join("")}
        </div>
      </div>

      <div class="card form-stack" style="justify-content:space-between;">
        <div>
          <div class="section-header">
            <h3>Savings Vault</h3>
            <span class="status-tag active">${escapeHtml(dash.savings_summary.annual_interest_rate)}% p.a.</span>
          </div>
          <div style="font-size:1.65rem; font-weight:800; color:var(--navy); margin:6px 0;">
            ${appState.hideBalance ? "&#8358; ••••••" : formatNGN(dash.savings_summary.balance)}
          </div>
          <p class="muted-copy">${dash.savings_summary.goals_count} active savings goal(s) in PostgreSQL.</p>
        </div>
        <div class="grid-2 compact-grid">
          <button id="dash-savings-btn" type="button" class="btn btn-primary btn-pill">Open Savings</button>
          <button id="dash-acct-btn" type="button" class="btn btn-outline-blue btn-pill">Account Info</button>
        </div>
      </div>
    </section>
  `;

  wireTransactionClicks(root);

  const dashSoundBtn = document.getElementById("dash-sound-btn");
  if (dashSoundBtn) {
    dashSoundBtn.addEventListener("click", () => {
      const muted = toggleSoundMuted();
      dashSoundBtn.innerHTML = muted ? icon("volumeX", 18) : icon("volume2", 18);
      dashSoundBtn.classList.toggle("is-muted", muted);
      dashSoundBtn.setAttribute("aria-label", muted ? "Unmute transaction sounds" : "Mute transaction sounds");
      showToast(muted ? "Transaction sounds muted." : "Transaction sounds enabled.", "info");
    });
  }
  document.getElementById("dash-notif-btn").addEventListener("click", () => navigate("notifications"));
  document.getElementById("dash-profile-btn").addEventListener("click", () => navigate("profile"));

  document.getElementById("toggle-balance-btn").addEventListener("click", async () => {
    appState.hideBalance = !appState.hideBalance;
    await renderDashboard(root, navigate, refreshChrome);
  });

  document.getElementById("copy-acct-btn").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(dash.account.account_number);
      showToast(`Account ${dash.account.account_number} copied.`, "success");
    } catch {
      showToast(`Account number: ${dash.account.account_number}`, "info");
    }
  });

  document.getElementById("hero-add-money-btn").addEventListener("click", () => navigate("add-money"));
  document.getElementById("qa-transfer").addEventListener("click", () => navigate("transfers"));
  document.getElementById("qa-add-money").addEventListener("click", () => navigate("add-money"));
  document.getElementById("qa-withdraw").addEventListener("click", () => navigate("withdraw"));
  document.getElementById("qa-airtime").addEventListener("click", () => navigate("payments:airtime"));
  document.getElementById("qa-data").addEventListener("click", () => navigate("payments:data"));
  document.getElementById("qa-electricity").addEventListener("click", () => navigate("payments:electricity"));
  document.getElementById("qa-tv").addEventListener("click", () => navigate("payments:television"));
  document.getElementById("qa-savings").addEventListener("click", () => navigate("savings"));
  document.getElementById("dash-history-btn").addEventListener("click", () => navigate("history"));
  document.getElementById("dash-savings-btn").addEventListener("click", () => navigate("savings"));
  document.getElementById("dash-acct-btn").addEventListener("click", () => navigate("account-details"));
}

export async function renderAccountDetails(root, navigate) {
  const acct = await apiRequest("/api/accounts/me");
  const me = appState.user;
  const verifCount = (me.email_verified ? 1 : 0) + (me.phone_verified ? 1 : 0);

  root.innerHTML = `
    <section class="card mobile-screen-card form-stack">
      <div class="section-header">
        <div style="display:flex; align-items:center; gap:10px;">
          <button type="button" class="back-arrow-btn" id="acct-back-btn" aria-label="Back">${icon("arrowLeft", 20)}</button>
          <h3 style="margin:0;">Account Details</h3>
        </div>
        <span class="status-tag verified">${me.email_verified ? "Email Verified" : "Phone Verified"}</span>
      </div>
      <div>
        <small style="color:var(--muted);">Verification Progress</small>
        <div class="progress-track">
          <div class="progress-fill" style="width:${verifCount >= 2 ? "100" : "75"}%"></div>
        </div>
        <small style="color:var(--muted);">
          Email: ${me.email_verified ? "Verified" : "Unverified"} &bull; Phone: ${me.phone_verified ? "Verified" : "Registered (Unverified)"}
        </small>
      </div>
      <div class="summary-blue-card">
        <div class="summary-kv-row"><span class="summary-kv-left">BraveBank Account Number</span><strong class="summary-kv-val">${escapeHtml(acct.account_number)}</strong></div>
        <div class="summary-kv-row"><span class="summary-kv-left">Account Holder</span><strong class="summary-kv-val">${escapeHtml(acct.account_name)}</strong></div>
        <div class="summary-kv-row"><span class="summary-kv-left">Primary Currency</span><strong class="summary-kv-val">NGN (&#8358;)</strong></div>
        <div class="summary-kv-row"><span class="summary-kv-left">Account Type</span><strong class="summary-kv-val">Demo Account (Simulated Funds)</strong></div>
        <div class="summary-kv-row"><span class="summary-kv-left">Available Balance</span><strong class="summary-kv-val">${formatNGN(acct.available_balance)}</strong></div>
        <div class="summary-kv-row"><span class="summary-kv-left">Ledger Balance</span><strong class="summary-kv-val">${formatNGN(acct.ledger_balance)}</strong></div>
      </div>
      <div class="grid-2 compact-grid">
        <button id="acct-copy-btn" type="button" class="btn btn-primary btn-pill">Copy Account</button>
        <button id="acct-stmt-btn" type="button" class="btn btn-outline-blue btn-pill">View History</button>
      </div>
    </section>
  `;

  document.getElementById("acct-back-btn").addEventListener("click", () => navigate("dashboard"));
  document.getElementById("acct-copy-btn").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(acct.account_number);
      showToast("Account number copied.", "success");
    } catch {
      showToast(`Account number: ${acct.account_number}`, "info");
    }
  });
  document.getElementById("acct-stmt-btn").addEventListener("click", () => navigate("history"));
}
