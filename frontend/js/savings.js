/** Savings Vault goals, contributions, and simulated interest credits. */

import { apiRequest } from "./api.js";
import { icon } from "./icons.js";
import { escapeHtml, formatNGN } from "./state.js";
import {
  openReceiptModal,
  openTransactionFailureModal,
  showToast,
  withButtonLoading,
} from "./ui.js";

export async function renderSavings(root, navigate) {
  const data = await apiRequest("/api/savings");
  const acct = data.savings_account;

  root.innerHTML = `
    <section class="balance-hero-card">
      <div class="balance-card-top">
        <div class="balance-label-row">
          <button type="button" class="eye-inline-btn" id="sav-back-btn" aria-label="Back to Home">${icon("arrowLeft", 15)}</button>
          <span>Savings Vault (${escapeHtml(acct.account_number)})</span>
        </div>
        <span class="acct-chip-copy">${escapeHtml(acct.annual_interest_rate)}% p.a.</span>
      </div>
      <div class="hero-balance-figure">${formatNGN(acct.balance)}</div>
      <div class="balance-card-top">
        <small style="color:rgba(255,255,255,0.88);">Accrued Interest: ${formatNGN(acct.accrued_interest)}</small>
        <button id="sim-interest-btn" type="button" class="hero-add-money-btn" style="padding:7px 14px; font-size:0.78rem;">
          Simulate Interest
        </button>
      </div>
    </section>

    <div class="grid-2">
      <section class="card form-stack">
        <h3>Create Savings Goal</h3>
        <form id="create-goal-form" class="form-stack">
          <label class="field">
            <span>Goal Title</span>
            <input id="goal-title" type="text" required minlength="2" placeholder="Rent &amp; Emergency Fund" />
          </label>
          <label class="field">
            <span>Target Amount (NGN)</span>
            <input id="goal-target" type="number" step="0.01" min="100" required placeholder="500000.00" />
          </label>
          <label class="field">
            <span>Target Date (Optional)</span>
            <input id="goal-date" type="date" />
          </label>
          <button type="submit" class="btn btn-primary btn-pill">Create Goal</button>
        </form>
      </section>

      <section class="card form-stack">
        <h3>Contribute to Goal</h3>
        <form id="contrib-goal-form" class="form-stack">
          <label class="field">
            <span>Select Goal</span>
            <select id="contrib-goal-id" required>
              ${
                data.goals.length
                  ? data.goals
                      .map((g) => `<option value="${escapeHtml(g.id)}">${escapeHtml(g.title)} (${formatNGN(g.current_amount)} / ${formatNGN(g.target_amount)})</option>`)
                      .join("")
                  : `<option value="">Create a goal first</option>`
              }
            </select>
          </label>
          <label class="field">
            <span>Amount (NGN)</span>
            <input id="contrib-amount" type="number" step="0.01" min="1" required placeholder="10000.00" />
          </label>
          <label class="field">
            <span>4-Digit Transaction PIN</span>
            <input id="contrib-pin" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="4-digit PIN" />
          </label>
          <button type="submit" class="btn btn-primary btn-pill" ${data.goals.length ? "" : "disabled"}>Contribute</button>
        </form>
      </section>
    </div>

    <section class="grid-3">
      ${
        data.goals.length
          ? data.goals
              .map(
                (g) => `
            <div class="card">
              <div class="section-header">
                <h3>${escapeHtml(g.title)}</h3>
                <span class="status-tag ${escapeHtml(g.status)}">${escapeHtml(g.status)}</span>
              </div>
              <p style="margin:6px 0;"><strong>${formatNGN(g.current_amount)}</strong> of ${formatNGN(g.target_amount)}</p>
              <div class="progress-track">
                <div class="progress-fill" style="width:${Math.min(100, g.progress_percent)}%"></div>
              </div>
              <small style="color:var(--muted);">${g.progress_percent.toFixed(1)}% funded</small>
            </div>`
              )
              .join("")
          : `<div class="card empty-state" style="grid-column:1 / -1;">No savings goals created yet.</div>`
      }
    </section>
  `;

  document.getElementById("sav-back-btn").addEventListener("click", () => navigate("dashboard"));

  document.getElementById("sim-interest-btn").addEventListener("click", async (e) => {
    await withButtonLoading(e.currentTarget, "Calculating...", async () => {
      try {
        const res = await apiRequest("/api/savings/simulate-interest", { method: "POST" });
        showToast(`Simulated interest ${formatNGN(res.interest_credited)} credited.`, "success");
        await renderSavings(root, navigate);
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  });

  document.getElementById("create-goal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await apiRequest("/api/savings/goals", {
        method: "POST",
        body: JSON.stringify({
          title: document.getElementById("goal-title").value,
          target_amount: document.getElementById("goal-target").value,
          target_date: document.getElementById("goal-date").value || null,
        }),
      });
      showToast("Savings goal created.", "success");
      await renderSavings(root, navigate);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("contrib-goal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pin = document.getElementById("contrib-pin").value.trim();
    if (!/^\d{4}$/.test(pin)) {
      showToast("Enter your 4-digit numeric transaction PIN.", "error");
      return;
    }
    const btn = e.target.querySelector("button[type='submit']");
    await withButtonLoading(btn, "Contributing...", async () => {
      try {
        const res = await apiRequest("/api/savings/contribute", {
          method: "POST",
          body: JSON.stringify({
            goal_id: document.getElementById("contrib-goal-id").value,
            amount: document.getElementById("contrib-amount").value,
            pin,
          }),
        });
        openReceiptModal({
          reference: res.transaction_reference,
          status: "completed",
          category: "savings_contribution",
          direction: "debit",
          amount: document.getElementById("contrib-amount").value,
          fee: "0.00",
          counterparty_name: "BraveBank Savings Vault",
          counterparty_account: acct.account_number,
          counterparty_bank: "BRAVEBANK",
          narration: "Savings contribution",
          created_at: new Date().toISOString(),
        });
        await renderSavings(root, navigate);
      } catch (err) {
        openTransactionFailureModal("Contribution Failed", err.message);
      }
    });
  });
}
