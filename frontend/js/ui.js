/** Reusable BraveBank UI helpers: toasts, loading states, Transfer Review, Transaction Success/Failure, and Terms modal. */

import { triggerTransferSuccessCelebration } from "./effects.js";
import { icon } from "./icons.js";
import { escapeHtml, formatDateTime, formatNGN } from "./state.js";

const toastContainer = document.getElementById("toast-container");
const modal = document.getElementById("app-modal");
const modalHeader = document.getElementById("modal-header");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const modalCloseBtn = document.getElementById("modal-close-btn");

modalCloseBtn.addEventListener("click", () => modal.close());
modal.addEventListener("click", (event) => {
  if (event.target === modal) modal.close();
});

export function showToast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  toastContainer.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 4500);
}

export async function withButtonLoading(button, labelDuringLoad, fn) {
  if (!button) return fn();
  const originalHtml = button.innerHTML;
  button.disabled = true;
  button.textContent = labelDuringLoad;
  try {
    return await fn();
  } finally {
    button.disabled = false;
    button.innerHTML = originalHtml;
  }
}

export function openModal(title, htmlContent, headerVariant = "") {
  modalTitle.textContent = title;
  modalHeader.className = `modal-header ${headerVariant}`.trim();
  modalBody.innerHTML = htmlContent;
  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.setAttribute("open", "true");
  }
}

export function closeModal() {
  if (modal.open) modal.close();
}

export function openTermsModal() {
  openModal(
    "BraveBank Terms & Prototype Disclosure",
    `
      <div class="form-stack">
        <p class="muted-copy">
          BraveBank is a simulated Nigerian digital banking prototype engineered with FastAPI, PostgreSQL, and Argon2 security.
        </p>
        <div class="summary-blue-card">
          <div class="summary-kv-row">
            <span class="summary-kv-left">${icon("shieldCheck", 16)} <span>Simulated Funds</span></span>
            <span class="summary-kv-val">No real money moves</span>
          </div>
          <div class="summary-kv-row">
            <span class="summary-kv-left">${icon("lock", 16)} <span>Credentials &amp; PIN</span></span>
            <span class="summary-kv-val">Argon2id hashed</span>
          </div>
          <div class="summary-kv-row">
            <span class="summary-kv-left">${icon("fileText", 16)} <span>Account Ledger</span></span>
            <span class="summary-kv-val">Atomic PostgreSQL</span>
          </div>
        </div>
        <button id="terms-close-btn" type="button" class="btn btn-primary btn-pill btn-full">Got It</button>
      </div>
    `
  );
  document.getElementById("terms-close-btn").addEventListener("click", closeModal);
}

export function openTransactionFailureModal(title, message) {
  openModal(
    "Transaction Declined",
    `
      <div class="form-stack" style="text-align:center;">
        <div class="failure-check-circle">${icon("x", 32)}</div>
        <h3 style="margin:0; font-size:1.2rem; color:var(--navy);">${escapeHtml(title || "Transaction Failed")}</h3>
        <p class="muted-copy">${escapeHtml(message || "Unable to complete your transaction. Your account balance was not changed.")}</p>
        <button id="tx-fail-close-btn" type="button" class="btn btn-primary btn-pill btn-full">Try Again</button>
      </div>
    `,
    "error-crimson"
  );
  document.getElementById("tx-fail-close-btn").addEventListener("click", closeModal);
}

export function openTransferReviewModal({
  amount,
  recipientName,
  accountNumber,
  bankName,
  narration,
  onConfirmWithPin,
}) {
  openModal(
    "Transfer Review",
    `
      <div class="receipt-hero">
        <div class="blue-circle-badge" style="margin:0 auto 10px;">${icon("send", 24)}</div>
        <div style="font-size:0.84rem; color:var(--muted);">Transfer Amount</div>
        <div style="font-size:1.95rem; font-weight:800; color:var(--navy);">${formatNGN(amount)}</div>
      </div>

      <div class="summary-blue-card" style="margin-bottom:16px;">
        <div class="summary-kv-row">
          <span class="summary-kv-left">${icon("user", 16)} <span>Recipient</span></span>
          <span class="summary-kv-val">${escapeHtml(recipientName)}</span>
        </div>
        <div class="summary-kv-row">
          <span class="summary-kv-left">${icon("hash", 16)} <span>Account</span></span>
          <span class="summary-kv-val">${escapeHtml(accountNumber)}</span>
        </div>
        <div class="summary-kv-row">
          <span class="summary-kv-left">${icon("building2", 16)} <span>Bank</span></span>
          <span class="summary-kv-val">${escapeHtml(bankName)}</span>
        </div>
        <div class="summary-kv-row">
          <span class="summary-kv-left">${icon("receipt", 16)} <span>Transfer Fee</span></span>
          <span class="summary-kv-val">${formatNGN(0)}</span>
        </div>
        <div class="summary-kv-row">
          <span class="summary-kv-left">${icon("fileText", 16)} <span>Narration</span></span>
          <span class="summary-kv-val">${escapeHtml(narration)}</span>
        </div>
      </div>

      <form id="review-pin-form" class="form-stack">
        <label class="field">
          <span>Enter 4-Digit Transaction PIN to Authorize</span>
          <div class="icon-input-box">
            <span class="input-left-icon">${icon("keyRound", 17)}</span>
            <input id="review-pin-input" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="4-digit PIN" />
          </div>
        </label>
        <div class="grid-2 compact-grid">
          <button id="review-cancel-btn" type="button" class="btn btn-outline-blue btn-pill">Cancel</button>
          <button type="submit" class="btn btn-primary btn-pill">Confirm Transfer</button>
        </div>
      </form>
    `,
    "review-navy"
  );

  document.getElementById("review-cancel-btn").addEventListener("click", closeModal);
  document.getElementById("review-pin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pin = document.getElementById("review-pin-input").value.trim();
    if (!/^\d{4}$/.test(pin)) {
      showToast("Enter your 4-digit numeric transaction PIN.", "error");
      return;
    }
    const btn = e.target.querySelector("button[type='submit']");
    await withButtonLoading(btn, "Authorizing...", async () => {
      await onConfirmWithPin(pin);
    });
  });
}

function headingForTx(tx) {
  if (tx.category === "demo_funding") return "Demo Balance Credited!";
  if (tx.category === "deposit") return "Deposit Successful!";
  if (tx.category === "withdrawal") return "Withdrawal Successful!";
  if (tx.category === "bill_payment") return "Payment Successful!";
  if (tx.category === "savings_contribution") return "Savings Credited!";
  return "Transfer Successful!";
}

function summaryLineForTx(tx) {
  const amt = formatNGN(tx.amount);
  if (tx.category === "demo_funding") return `Your account was initialized with ${amt} in simulated demo funds.`;
  if (tx.category === "deposit") return `Your deposit of ${amt} was successful.`;
  if (tx.category === "withdrawal") return `Your withdrawal of ${amt} was successful.`;
  if (tx.category === "bill_payment") return `Your bill payment of ${amt} was successful.`;
  if (tx.category === "savings_contribution") return `Your savings contribution of ${amt} was successful.`;
  return `Your transfer of ${amt} was successful.`;
}

export function openReceiptModal(tx, ledgerEntries = [], extraInfo = {}) {
  const tokenLine = extraInfo.token
    ? `<div class="summary-kv-row">
         <span class="summary-kv-left">${icon("keyRound", 16)} <span>Token / PIN</span></span>
         <span class="summary-kv-val"><code>${escapeHtml(extraInfo.token)}</code></span>
       </div>`
    : "";

  const ledgerHtml = ledgerEntries.length
    ? `
      <div style="margin-top:12px; padding:12px; border-radius:14px; background:#f8fafc; border:1px solid var(--border); text-align:left;">
        <strong style="font-size:0.8rem; color:var(--navy);">Ledger Entries</strong>
        <div class="receipt-rows" style="margin-top:8px;">
          ${ledgerEntries
            .map(
              (entry) => `
            <div class="receipt-row">
              <span>${escapeHtml(entry.entry_type.toUpperCase())} (${formatNGN(entry.balance_before)} &rarr; ${formatNGN(entry.balance_after)})</span>
              <strong>${formatNGN(entry.amount)}</strong>
            </div>`
            )
            .join("")}
        </div>
      </div>`
    : "";

  openModal(
    "Transaction Receipt",
    `
      <div class="form-stack" style="text-align:center;">
        <div class="success-check-halo">
          <div class="success-check-circle">${icon("check", 32)}</div>
        </div>
        <h3 style="margin:0; font-size:1.35rem; font-weight:800; color:var(--navy);">${escapeHtml(headingForTx(tx))}</h3>
        <p class="muted-copy" style="color:var(--navy); font-weight:500;">
          ${escapeHtml(summaryLineForTx(tx))}
        </p>

        <div class="summary-blue-card" style="text-align:left; margin-top:4px;">
          <div class="summary-kv-row">
            <span class="summary-kv-left">${icon("user", 16)} <span>Transaction ID</span></span>
            <span class="summary-kv-val">${escapeHtml(tx.reference)}</span>
          </div>
          <div class="summary-kv-row">
            <span class="summary-kv-left">${icon("history", 16)} <span>Date &amp; Time</span></span>
            <span class="summary-kv-val">${escapeHtml(formatDateTime(tx.created_at))}</span>
          </div>
          ${
            tx.counterparty_name
              ? `<div class="summary-kv-row">
                   <span class="summary-kv-left">${icon("building2", 16)} <span>Recipient</span></span>
                   <span class="summary-kv-val">${escapeHtml(tx.counterparty_name)}${tx.counterparty_bank ? ` (${escapeHtml(tx.counterparty_bank)})` : ""}</span>
                 </div>`
              : ""
          }
          ${
            tx.counterparty_account
              ? `<div class="summary-kv-row">
                   <span class="summary-kv-left">${icon("hash", 16)} <span>Account / Ref</span></span>
                   <span class="summary-kv-val">${escapeHtml(tx.counterparty_account)}</span>
                 </div>`
              : ""
          }
          <div class="summary-kv-row">
            <span class="summary-kv-left">${icon("shieldCheck", 16)} <span>Status</span></span>
            <span class="summary-kv-val" style="color:var(--emerald); text-transform:capitalize;">${escapeHtml(tx.status)}</span>
          </div>
          ${tokenLine}
        </div>

        ${ledgerHtml}

        <div class="form-stack" style="margin-top:6px; gap:10px;">
          <button id="receipt-done-btn" type="button" class="btn btn-primary btn-pill btn-full">Done</button>
          <button id="share-receipt-btn" type="button" class="btn btn-outline-blue btn-pill btn-full">
            ${icon("share2", 17)}
            <span>Share Receipt</span>
          </button>
        </div>
      </div>
    `,
    "receipt-emerald"
  );

  if (
    extraInfo.celebrateInternalTransfer === true &&
    tx &&
    tx.category === "internal_transfer" &&
    tx.status === "completed"
  ) {
    triggerTransferSuccessCelebration(tx);
  }

  document.getElementById("receipt-done-btn").addEventListener("click", closeModal);
  document.getElementById("share-receipt-btn").addEventListener("click", async () => {
    const content = [
      "BRAVEBANK — TRANSACTION RECEIPT",
      "================================",
      `Transaction ID: ${tx.reference}`,
      `Status:         ${tx.status}`,
      `Category:       ${tx.category}`,
      `Direction:      ${tx.direction}`,
      `Amount:         ${formatNGN(tx.amount)}`,
      `Fee:            ${formatNGN(tx.fee)}`,
      `Recipient:      ${tx.counterparty_name || "-"}`,
      `Account/Ref:    ${tx.counterparty_account || "-"}`,
      `Bank:           ${tx.counterparty_bank || "BRAVEBANK"}`,
      `Narration:      ${tx.narration}`,
      extraInfo.token ? `Token/Receipt:  ${extraInfo.token}` : null,
      `Date & Time:    ${formatDateTime(tx.created_at)}`,
      "================================",
      "BraveBank — Banking Without Limits (Simulated Prototype)",
    ]
      .filter(Boolean)
      .join("\n");

    if (navigator.share) {
      try {
        await navigator.share({ title: `BraveBank Receipt ${tx.reference}`, text: content });
        return;
      } catch {
        // User dismissed native share sheet or browser restricted share; fall back to download/copy
      }
    }

    try {
      await navigator.clipboard.writeText(content);
      showToast("Receipt copied and downloaded.", "success");
    } catch {
      showToast("Receipt downloaded.", "success");
    }

    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${tx.reference}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });
}
