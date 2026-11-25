/** Shared transaction list rendering + Transfer, Add Money, and Withdraw screens. */

import { apiRequest } from "./api.js";
import { icon } from "./icons.js";
import {
  appState,
  escapeHtml,
  formatDateTime,
  formatNGN,
  newIdempotencyKey,
} from "./state.js";
import {
  closeModal,
  openModal,
  openReceiptModal,
  openTransactionFailureModal,
  openTransferReviewModal,
  showToast,
  withButtonLoading,
} from "./ui.js";

export async function openTransactionDetail(txId) {
  try {
    const detail = await apiRequest(`/api/transactions/${txId}`);
    openReceiptModal(detail.transaction, detail.ledger_entries);
  } catch (err) {
    showToast(err.message, "error");
  }
}

export function renderTransactionCards(transactions) {
  if (!transactions.length) {
    return `
      <div class="empty-state">
        <div class="empty-icon-circle">${icon("history", 24)}</div>
        <strong>No transactions yet</strong>
        <p class="muted-copy" style="margin-top:4px;">Use Add Money or Transfer to see your live transaction history.</p>
      </div>`;
  }
  return `
    <div class="tx-list">
      ${transactions
        .map(
          (tx) => `
        <div class="tx-row-item" data-tx-id="${escapeHtml(tx.id)}">
          <div class="tx-left">
            <div class="tx-icon-circle ${tx.direction === "credit" ? "credit" : "debit"}">
              ${tx.direction === "credit" ? icon("arrowUp", 18) : icon("arrowUp", 18)}
            </div>
            <div class="tx-meta">
              <strong>${escapeHtml(tx.narration)}</strong>
              <small>${escapeHtml(formatDateTime(tx.created_at))} &middot; <span style="text-transform:capitalize;">${escapeHtml(tx.status)}</span></small>
            </div>
          </div>
          <div class="tx-amount ${tx.direction === "credit" ? "credit" : "debit"}">
            ${tx.direction === "credit" ? "+ " : "- "}${formatNGN(tx.amount)}
          </div>
        </div>`
        )
        .join("")}
    </div>
  `;
}

export function wireTransactionClicks(container) {
  container.querySelectorAll("[data-tx-id]").forEach((row) => {
    row.addEventListener("click", () => openTransactionDetail(row.dataset.txId));
  });
}

function openDepositModal(accountNumber, onSuccess) {
  openModal(
    "Add Money",
    `
      <form id="modal-deposit-form" class="form-stack">
        <p class="muted-copy">
          Simulate an instant NGN deposit into BraveBank Account <strong>${escapeHtml(accountNumber)}</strong>.
        </p>
        <div class="amount-chips">
          <button type="button" class="chip-btn" data-chip="5000">&#8358;5,000</button>
          <button type="button" class="chip-btn" data-chip="20000">&#8358;20,000</button>
          <button type="button" class="chip-btn" data-chip="50000">&#8358;50,000</button>
          <button type="button" class="chip-btn" data-chip="100000">&#8358;100,000</button>
        </div>
        <label class="field">
          <span>Amount (NGN)</span>
          <input id="dep-amount" type="number" step="0.01" min="1" required placeholder="25000.00" />
        </label>
        <label class="field">
          <span>Narration</span>
          <input id="dep-narration" type="text" maxlength="200" value="Simulated NGN Deposit" />
        </label>
        <button type="submit" class="btn btn-primary btn-pill btn-full">Confirm Deposit</button>
      </form>
    `
  );
  document.querySelectorAll("[data-chip]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById("dep-amount").value = btn.dataset.chip;
    });
  });
  document.getElementById("modal-deposit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button[type='submit']");
    await withButtonLoading(btn, "Processing...", async () => {
      try {
        const tx = await apiRequest("/api/accounts/deposit", {
          method: "POST",
          body: JSON.stringify({
            amount: document.getElementById("dep-amount").value,
            narration: document.getElementById("dep-narration").value,
            idempotency_key: newIdempotencyKey("dep"),
          }),
        });
        closeModal();
        openReceiptModal(tx);
        await onSuccess();
      } catch (err) {
        openTransactionFailureModal("Deposit Failed", err.message);
      }
    });
  });
}

export async function renderAddMoney(root, navigate) {
  const acct = await apiRequest("/api/accounts/me");
  root.innerHTML = `
    <section class="card mobile-screen-card form-stack">
      <div class="screen-sub-header">
        <button type="button" class="back-arrow-btn" id="add-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
        <h2>Add Money</h2>
      </div>

      <div class="hero-badge-center">
        <div class="blue-circle-badge">${icon("plusCircle", 26)}</div>
        <h3>Fund BraveBank Account</h3>
        <p>Available Balance: <strong>${formatNGN(acct.available_balance)}</strong> &middot; Acct ${escapeHtml(acct.account_number)}</p>
      </div>

      <button type="button" class="option-row" id="opt-card-topup">
        <div style="display:flex; align-items:center; gap:12px;">
          <span class="qa-icon-badge">${icon("creditCard", 19)}</span>
          <div>
            <strong>Simulated Debit Card Top-Up</strong><br/>
            <small style="color:var(--muted);">Instant simulated NGN funding into your ledger</small>
          </div>
        </div>
        ${icon("chevronRight", 18)}
      </button>

      <button type="button" class="option-row" id="opt-bank-copy">
        <div style="display:flex; align-items:center; gap:12px;">
          <span class="qa-icon-badge">${icon("building2", 19)}</span>
          <div>
            <strong>Bank Transfer to BraveBank Account</strong><br/>
            <small style="color:var(--muted);">${escapeHtml(acct.account_number)} &middot; ${escapeHtml(acct.account_name)}</small>
          </div>
        </div>
        ${icon("copy", 18)}
      </button>

      <button type="button" class="option-row" id="opt-direct-deposit">
        <div style="display:flex; align-items:center; gap:12px;">
          <span class="qa-icon-badge">${icon("arrowDownLeft", 19)}</span>
          <div>
            <strong>Simulated Direct Deposit</strong><br/>
            <small style="color:var(--muted);">Credit salary or prototype funds atomically</small>
          </div>
        </div>
        ${icon("chevronRight", 18)}
      </button>
    </section>
  `;

  document.getElementById("add-back-btn").addEventListener("click", () => navigate("dashboard"));
  document.getElementById("opt-card-topup").addEventListener("click", () =>
    openDepositModal(acct.account_number, () => navigate("dashboard"))
  );
  document.getElementById("opt-direct-deposit").addEventListener("click", () =>
    openDepositModal(acct.account_number, () => navigate("dashboard"))
  );
  document.getElementById("opt-bank-copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(acct.account_number);
      showToast(`Copied account number ${acct.account_number}.`, "success");
    } catch {
      showToast(`Account number: ${acct.account_number}`, "info");
    }
  });
}

export async function renderWithdraw(root, navigate) {
  const acct = await apiRequest("/api/accounts/me");
  root.innerHTML = `
    <section class="card mobile-screen-card form-stack">
      <div class="screen-sub-header">
        <button type="button" class="back-arrow-btn" id="wd-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
        <h2>Withdraw</h2>
      </div>

      <div class="hero-badge-center">
        <div class="blue-circle-badge">${icon("wallet", 24)}</div>
        <h3>Withdraw Funds</h3>
        <p>Available Balance: <strong>${formatNGN(acct.available_balance)}</strong></p>
      </div>

      <form id="withdraw-screen-form" class="form-stack">
        <label class="field">
          <span>Destination Channel</span>
          <select id="wd-channel">
            <option value="Simulated Agent / ATM Cash-Out">Simulated Agent / ATM Cash-Out</option>
            <option value="Simulated Linked Bank Payout">Simulated Linked Bank Payout</option>
          </select>
        </label>

        <div class="amount-chips">
          <button type="button" class="chip-btn" data-wd-chip="2000">&#8358;2,000</button>
          <button type="button" class="chip-btn" data-wd-chip="5000">&#8358;5,000</button>
          <button type="button" class="chip-btn" data-wd-chip="10000">&#8358;10,000</button>
          <button type="button" class="chip-btn" data-wd-chip="20000">&#8358;20,000</button>
        </div>

        <label class="field">
          <span>Amount (NGN)</span>
          <input id="wd-amount" type="number" step="0.01" min="1" required placeholder="Enter amount" />
        </label>

        <label class="field">
          <span>Narration (Optional)</span>
          <input id="wd-narration" type="text" maxlength="200" placeholder="Add a note" />
        </label>

        <label class="field">
          <span>4-Digit Transaction PIN</span>
          <div class="icon-input-box">
            <span class="input-left-icon">${icon("keyRound", 17)}</span>
            <input id="wd-pin" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="Enter 4-digit PIN" />
          </div>
        </label>

        <button type="submit" class="btn btn-primary btn-pill btn-full">Withdraw Funds</button>
      </form>
    </section>
  `;

  document.getElementById("wd-back-btn").addEventListener("click", () => navigate("dashboard"));
  root.querySelectorAll("[data-wd-chip]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById("wd-amount").value = btn.dataset.wdChip;
    });
  });

  document.getElementById("withdraw-screen-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pin = document.getElementById("wd-pin").value.trim();
    if (!/^\d{4}$/.test(pin)) {
      showToast("Enter your 4-digit numeric transaction PIN.", "error");
      return;
    }
    const channel = document.getElementById("wd-channel").value;
    const note = document.getElementById("wd-narration").value.trim();
    const btn = e.target.querySelector("button[type='submit']");

    await withButtonLoading(btn, "Processing...", async () => {
      try {
        const tx = await apiRequest("/api/accounts/withdraw", {
          method: "POST",
          body: JSON.stringify({
            amount: document.getElementById("wd-amount").value,
            narration: note || channel,
            pin,
            idempotency_key: newIdempotencyKey("wdr"),
          }),
        });
        openReceiptModal(tx);
        await renderWithdraw(root, navigate);
      } catch (err) {
        openTransactionFailureModal("Withdrawal Failed", err.message);
      }
    });
  });
}

export async function renderTransfers(root, navigate) {
  const [banks, beneficiaries] = await Promise.all([
    apiRequest("/api/transfers/banks"),
    apiRequest("/api/transfers/beneficiaries"),
  ]);
  appState.banks = banks;

  let resolvedRecipient = null;

  root.innerHTML = `
    <section class="card mobile-screen-card form-stack">
      <div class="screen-sub-header">
        <button type="button" class="back-arrow-btn" id="tr-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
        <h2>Transfer</h2>
      </div>

      <div class="hero-badge-center">
        <div class="blue-circle-badge">${icon("send", 24)}</div>
        <h3>Send Money</h3>
        <p>Fast. Safe. Reliable.</p>
      </div>

      <form id="unified-transfer-form" class="form-stack">
        <label class="field">
          <span>Recipient Account</span>
          <div class="account-picker-wrap">
            <input id="tr-account" type="text" required placeholder="Enter account number (or BraveBank phone)" />
            <button id="open-ben-picker-btn" type="button" class="picker-icon-btn" title="Choose saved beneficiary" aria-label="Choose saved beneficiary">
              ${icon("bookUser", 20)}
            </button>
          </div>
        </label>

        <label class="field">
          <span>Bank</span>
          <select id="tr-bank" required>
            <option value="">Select Bank</option>
            <option value="BRAVE">BraveBank (Instant Internal)</option>
            ${banks.map((b) => `<option value="${escapeHtml(b.code)}">${escapeHtml(b.name)}</option>`).join("")}
          </select>
        </label>

        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
          <div id="tr-resolved-box" class="verified-recipient-pill hidden" style="flex:1;"></div>
          <button id="tr-verify-btn" type="button" class="btn btn-outline-blue btn-sm">Verify Recipient</button>
        </div>

        <div class="amount-chips">
          <button type="button" class="chip-btn" data-tr-chip="1000">&#8358;1,000</button>
          <button type="button" class="chip-btn" data-tr-chip="5000">&#8358;5,000</button>
          <button type="button" class="chip-btn" data-tr-chip="10000">&#8358;10,000</button>
          <button type="button" class="chip-btn" data-tr-chip="50000">&#8358;50,000</button>
        </div>

        <label class="field">
          <span>Amount</span>
          <input id="tr-amount" type="number" step="0.01" min="1" required placeholder="Enter amount" />
        </label>

        <label class="field">
          <span>Narration (Optional)</span>
          <input id="tr-narration" type="text" maxlength="200" placeholder="Add a note" />
        </label>

        <label style="display:flex; align-items:center; gap:8px; font-size:0.84rem; color:var(--muted);">
          <input id="tr-save-ben" type="checkbox" style="width:auto;" />
          <span>Save recipient to beneficiaries</span>
        </label>

        <button id="tr-continue-btn" type="submit" class="btn btn-primary btn-pill btn-full">Continue</button>
      </form>
    </section>

    <section class="card mobile-screen-card">
      <div class="section-header">
        <h3>Saved Beneficiaries</h3>
        <span class="status-tag">${beneficiaries.length}</span>
      </div>
      ${
        beneficiaries.length
          ? `
        <div class="tx-list">
          ${beneficiaries
            .map(
              (b) => `
            <div class="tx-row-item" style="cursor:default;">
              <div class="tx-left">
                <div class="tx-icon-circle debit">${icon("user", 18)}</div>
                <div class="tx-meta">
                  <strong>${escapeHtml(b.account_name)}</strong>
                  <small>${escapeHtml(b.account_number)} &middot; ${escapeHtml(b.bank_name)}</small>
                </div>
              </div>
              <div style="display:flex; gap:6px;">
                <button type="button" class="btn btn-outline-blue btn-sm" data-use-ben="${escapeHtml(b.id)}">Use</button>
                <button type="button" class="btn btn-danger btn-sm" data-del-ben="${escapeHtml(b.id)}">Delete</button>
              </div>
            </div>`
            )
            .join("")}
        </div>`
          : `<div class="empty-state">No saved beneficiaries yet.</div>`
      }
    </section>
  `;

  const acctInput = document.getElementById("tr-account");
  const bankSelect = document.getElementById("tr-bank");
  const resolvedBox = document.getElementById("tr-resolved-box");

  async function resolveRecipient(silent = false) {
    const query = acctInput.value.trim();
    const bankCode = bankSelect.value;
    if (!query || !bankCode) {
      if (!silent) showToast("Enter a recipient account and select a bank.", "error");
      return null;
    }

    try {
      if (bankCode === "BRAVE") {
        const data = await apiRequest(`/api/transfers/lookup-internal?query=${encodeURIComponent(query)}`);
        resolvedRecipient = {
          is_internal: true,
          account_number: data.account_number,
          account_name: data.account_name,
          bank_code: "000",
          bank_name: "BRAVEBANK",
        };
      } else {
        if (!/^\d{10}$/.test(query)) {
          throw new Error("External bank transfers require a 10-digit NUBAN account number.");
        }
        const data = await apiRequest("/api/transfers/external/resolve", {
          method: "POST",
          body: JSON.stringify({ bank_code: bankCode, account_number: query }),
        });
        resolvedRecipient = {
          is_internal: false,
          account_number: data.account_number,
          account_name: data.account_name,
          bank_code: data.bank_code,
          bank_name: data.bank_name,
        };
      }
      resolvedBox.innerHTML = `${icon("check", 16)} <span>${escapeHtml(resolvedRecipient.account_name)} &middot; ${escapeHtml(resolvedRecipient.bank_name)}</span>`;
      resolvedBox.classList.remove("hidden");
      return resolvedRecipient;
    } catch (err) {
      resolvedRecipient = null;
      resolvedBox.classList.add("hidden");
      if (!silent) showToast(err.message, "error");
      return null;
    }
  }

  function applyBeneficiary(b) {
    acctInput.value = b.account_number;
    bankSelect.value = b.is_internal ? "BRAVE" : b.bank_code;
    resolvedRecipient = {
      is_internal: b.is_internal,
      account_number: b.account_number,
      account_name: b.account_name,
      bank_code: b.bank_code,
      bank_name: b.bank_name,
    };
    resolvedBox.innerHTML = `${icon("check", 16)} <span>${escapeHtml(b.account_name)} &middot; ${escapeHtml(b.bank_name)}</span>`;
    resolvedBox.classList.remove("hidden");
  }

  document.getElementById("tr-back-btn").addEventListener("click", () => navigate("dashboard"));
  document.getElementById("tr-verify-btn").addEventListener("click", () => resolveRecipient(false));

  acctInput.addEventListener("input", () => {
    resolvedRecipient = null;
    resolvedBox.classList.add("hidden");
    const digits = acctInput.value.trim();
    if (digits.length === 10 && /^\d{10}$/.test(digits) && bankSelect.value) {
      resolveRecipient(true);
    }
  });

  bankSelect.addEventListener("change", () => {
    resolvedRecipient = null;
    resolvedBox.classList.add("hidden");
    if (acctInput.value.trim().length >= 10 && bankSelect.value) {
      resolveRecipient(true);
    }
  });

  root.querySelectorAll("[data-tr-chip]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById("tr-amount").value = btn.dataset.trChip;
    });
  });

  document.getElementById("open-ben-picker-btn").addEventListener("click", () => {
    if (!beneficiaries.length) {
      showToast("No saved beneficiaries yet. Complete a transfer and check 'Save recipient'.", "info");
      return;
    }
    openModal(
      "Choose Beneficiary",
      `
        <div class="form-stack">
          ${beneficiaries
            .map(
              (b) => `
            <button type="button" class="option-row" data-pick-ben="${escapeHtml(b.id)}">
              <div>
                <strong>${escapeHtml(b.account_name)}</strong><br/>
                <small style="color:var(--muted);">${escapeHtml(b.account_number)} &middot; ${escapeHtml(b.bank_name)}</small>
              </div>
              ${icon("chevronRight", 18)}
            </button>`
            )
            .join("")}
        </div>
      `
    );
    document.querySelectorAll("[data-pick-ben]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const ben = beneficiaries.find((x) => x.id === btn.dataset.pickBen);
        if (ben) applyBeneficiary(ben);
        closeModal();
      });
    });
  });

  root.querySelectorAll("[data-use-ben]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const ben = beneficiaries.find((x) => x.id === btn.dataset.useBen);
      if (ben) {
        applyBeneficiary(ben);
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });
  });

  root.querySelectorAll("[data-del-ben]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiRequest(`/api/transfers/beneficiaries/${btn.dataset.delBen}`, { method: "DELETE" });
      showToast("Beneficiary removed.", "success");
      await renderTransfers(root, navigate);
    });
  });

  document.getElementById("unified-transfer-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!resolvedRecipient) {
      const resolved = await resolveRecipient(false);
      if (!resolved) return;
    }

    const amount = document.getElementById("tr-amount").value;
    const narration = document.getElementById("tr-narration").value.trim() || "BraveBank Transfer";
    const saveBen = document.getElementById("tr-save-ben").checked;

    openTransferReviewModal({
      amount,
      recipientName: resolvedRecipient.account_name,
      accountNumber: resolvedRecipient.account_number,
      bankName: resolvedRecipient.bank_name,
      narration,
      onConfirmWithPin: async (pin) => {
        try {
          const endpoint = resolvedRecipient.is_internal
            ? "/api/transfers/internal"
            : "/api/transfers/external";
          const bodyPayload = resolvedRecipient.is_internal
            ? {
                recipient_account_number: resolvedRecipient.account_number,
                amount,
                pin,
                narration,
                idempotency_key: newIdempotencyKey("int"),
              }
            : {
                bank_code: resolvedRecipient.bank_code,
                account_number: resolvedRecipient.account_number,
                account_name: resolvedRecipient.account_name,
                amount,
                pin,
                narration,
                idempotency_key: newIdempotencyKey("ext"),
              };

          const tx = await apiRequest(endpoint, {
            method: "POST",
            body: JSON.stringify(bodyPayload),
          });

          if (saveBen) {
            await apiRequest("/api/transfers/beneficiaries", {
              method: "POST",
              body: JSON.stringify({
                nickname: resolvedRecipient.account_name.split(" ")[0],
                account_number: resolvedRecipient.account_number,
                account_name: resolvedRecipient.account_name,
                bank_code: resolvedRecipient.bank_code,
                bank_name: resolvedRecipient.bank_name,
                is_internal: resolvedRecipient.is_internal,
              }),
            }).catch(() => {});
          }

          closeModal();
          openReceiptModal(tx);
          await renderTransfers(root, navigate);
        } catch (err) {
          openTransactionFailureModal("Transfer Failed", err.message);
        }
      },
    });
  });
}
