/** Nigerian bill payment screen: Airtime, Data plans, Electricity, TV packages, and Education. */

import { apiRequest } from "./api.js";
import { icon } from "./icons.js";
import { escapeHtml, formatNGN, newIdempotencyKey } from "./state.js";
import {
  openReceiptModal,
  openTransactionFailureModal,
  showToast,
  withButtonLoading,
} from "./ui.js";

const DATA_PLANS = [
  { label: "1GB Daily/Weekly — \u20A6500", amount: "500" },
  { label: "2.5GB Monthly — \u20A61,000", amount: "1000" },
  { label: "5GB Monthly — \u20A62,000", amount: "2000" },
  { label: "10GB Monthly — \u20A63,500", amount: "3500" },
  { label: "20GB Mega Plan — \u20A66,000", amount: "6000" },
];

const TV_PACKAGES = [
  { label: "Basic / Padi — \u20A63,600", amount: "3600" },
  { label: "Yanga / Jinja — \u20A65,100", amount: "5100" },
  { label: "Confam / Jolli — \u20A69,300", amount: "9300" },
  { label: "Compact / Max — \u20A615,700", amount: "15700" },
];

export async function renderPayments(root, navigate, initialCategory = "airtime") {
  const [providers, history] = await Promise.all([
    apiRequest("/api/bills/providers"),
    apiRequest("/api/bills/history"),
  ]);

  let activeCategory = providers[initialCategory] ? initialCategory : "airtime";

  root.innerHTML = `
    <div class="grid-2">
      <section class="card form-stack">
        <div class="screen-sub-header" style="margin-bottom:4px;">
          <button type="button" class="back-arrow-btn" id="bill-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
          <h2>Pay Bills (Simulated)</h2>
        </div>

        <div class="segmented" style="width:100%; overflow-x:auto;" role="tablist">
          <button type="button" class="seg-btn ${activeCategory === "airtime" ? "active" : ""}" data-bcat="airtime">Airtime</button>
          <button type="button" class="seg-btn ${activeCategory === "data" ? "active" : ""}" data-bcat="data">Data</button>
          <button type="button" class="seg-btn ${activeCategory === "electricity" ? "active" : ""}" data-bcat="electricity">Electricity</button>
          <button type="button" class="seg-btn ${activeCategory === "television" ? "active" : ""}" data-bcat="television">TV</button>
          <button type="button" class="seg-btn ${activeCategory === "education" ? "active" : ""}" data-bcat="education">Edu</button>
        </div>

        <form id="bill-pay-form" class="form-stack">
          <input id="bill-cat" type="hidden" value="${escapeHtml(activeCategory)}" />
          <label class="field">
            <span id="bill-provider-label">Network / Provider</span>
            <select id="bill-provider" required></select>
          </label>

          <div id="bill-extra-field" class="hidden"></div>

          <label class="field">
            <span id="bill-ref-label">Phone Number</span>
            <input id="bill-ref" type="text" required minlength="4" placeholder="08012345678" />
          </label>

          <div id="bill-quick-chips" class="amount-chips">
            <button type="button" class="chip-btn" data-bchip="500">&#8358;500</button>
            <button type="button" class="chip-btn" data-bchip="1000">&#8358;1,000</button>
            <button type="button" class="chip-btn" data-bchip="2000">&#8358;2,000</button>
            <button type="button" class="chip-btn" data-bchip="5000">&#8358;5,000</button>
          </div>

          <label class="field">
            <span>Amount (NGN)</span>
            <input id="bill-amount" type="number" step="0.01" min="50" required placeholder="2000.00" />
          </label>

          <label class="field">
            <span>4-Digit Transaction PIN</span>
            <div class="icon-input-box">
              <span class="input-left-icon">${icon("keyRound", 17)}</span>
              <input id="bill-pin" type="password" inputmode="numeric" maxlength="4" pattern="\\d{4}" required placeholder="Enter 4-digit PIN" />
            </div>
          </label>
          <button type="submit" class="btn btn-primary btn-pill btn-full">Pay Bill Now</button>
        </form>
      </section>

      <section class="card">
        <div class="section-header">
          <h3>Recent Bill Payments</h3>
          <span class="status-tag">${history.length}</span>
        </div>
        ${
          history.length
            ? `
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Reference</th>
                  <th>Token</th>
                  <th class="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                ${history
                  .map(
                    (h) => `
                  <tr>
                    <td><strong>${escapeHtml(h.provider)}</strong><br/><small>${escapeHtml(h.category)}</small></td>
                    <td>${escapeHtml(h.customer_reference)}</td>
                    <td><code>${escapeHtml(h.token_or_receipt)}</code></td>
                    <td class="num debit">${formatNGN(h.amount)}</td>
                  </tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>`
            : `<div class="empty-state">No bill payments recorded yet.</div>`
        }
      </section>
    </div>
  `;

  const catHidden = document.getElementById("bill-cat");
  const provSelect = document.getElementById("bill-provider");
  const refLabel = document.getElementById("bill-ref-label");
  const refInput = document.getElementById("bill-ref");
  const extraField = document.getElementById("bill-extra-field");
  const amountInput = document.getElementById("bill-amount");

  function syncCategoryUI(cat) {
    activeCategory = cat;
    catHidden.value = cat;
    root.querySelectorAll("[data-bcat]").forEach((b) => {
      b.classList.toggle("active", b.dataset.bcat === cat);
    });

    const list = providers[cat] || [];
    provSelect.innerHTML = list.map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");

    if (cat === "airtime") {
      refLabel.textContent = "Mobile Phone Number";
      refInput.placeholder = "08012345678";
      extraField.classList.add("hidden");
      extraField.innerHTML = "";
    } else if (cat === "data") {
      refLabel.textContent = "Mobile Phone Number";
      refInput.placeholder = "08012345678";
      extraField.classList.remove("hidden");
      extraField.innerHTML = `
        <label class="field">
          <span>Data Plan</span>
          <select id="bill-plan-select">
            <option value="">Choose data bundle...</option>
            ${DATA_PLANS.map((p) => `<option value="${p.amount}">${escapeHtml(p.label)}</option>`).join("")}
          </select>
        </label>`;
      document.getElementById("bill-plan-select").addEventListener("change", (ev) => {
        if (ev.target.value) amountInput.value = ev.target.value;
      });
    } else if (cat === "electricity") {
      refLabel.textContent = "Meter Number";
      refInput.placeholder = "45012349812";
      extraField.classList.remove("hidden");
      extraField.innerHTML = `
        <label class="field">
          <span>Meter Type</span>
          <select id="bill-meter-type">
            <option value="Prepaid">Prepaid Meter</option>
            <option value="Postpaid">Postpaid Meter</option>
          </select>
        </label>`;
    } else if (cat === "television") {
      refLabel.textContent = "Smartcard / IUC Number";
      refInput.placeholder = "7012345678";
      extraField.classList.remove("hidden");
      extraField.innerHTML = `
        <label class="field">
          <span>TV Bouquet / Package</span>
          <select id="bill-tv-pkg">
            <option value="">Choose TV package...</option>
            ${TV_PACKAGES.map((p) => `<option value="${p.amount}">${escapeHtml(p.label)}</option>`).join("")}
          </select>
        </label>`;
      document.getElementById("bill-tv-pkg").addEventListener("change", (ev) => {
        if (ev.target.value) amountInput.value = ev.target.value;
      });
    } else {
      refLabel.textContent = "Candidate / Registration Number";
      refInput.placeholder = "2026991045AB";
      extraField.classList.add("hidden");
      extraField.innerHTML = "";
    }
  }

  syncCategoryUI(activeCategory);

  document.getElementById("bill-back-btn").addEventListener("click", () => navigate("dashboard"));
  root.querySelectorAll("[data-bcat]").forEach((btn) => {
    btn.addEventListener("click", () => syncCategoryUI(btn.dataset.bcat));
  });
  root.querySelectorAll("[data-bchip]").forEach((btn) => {
    btn.addEventListener("click", () => {
      amountInput.value = btn.dataset.bchip;
    });
  });

  document.getElementById("bill-pay-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pin = document.getElementById("bill-pin").value.trim();
    if (!/^\d{4}$/.test(pin)) {
      showToast("Enter your 4-digit numeric transaction PIN.", "error");
      return;
    }
    const btn = e.target.querySelector("button[type='submit']");
    await withButtonLoading(btn, "Paying...", async () => {
      try {
        const res = await apiRequest("/api/bills/pay", {
          method: "POST",
          body: JSON.stringify({
            category: catHidden.value,
            provider: provSelect.value,
            customer_reference: refInput.value.trim(),
            amount: amountInput.value,
            pin,
            idempotency_key: newIdempotencyKey("bill"),
          }),
        });
        openReceiptModal(
          {
            reference: res.reference,
            status: res.status,
            category: "bill_payment",
            direction: "debit",
            amount: res.amount,
            fee: "0.00",
            counterparty_name: res.provider,
            counterparty_account: res.customer_reference,
            counterparty_bank: "Nigeria Billers",
            narration: `${res.category} - ${res.provider}`,
            created_at: res.created_at,
          },
          [],
          { token: res.token_or_receipt }
        );
        await renderPayments(root, navigate, activeCategory);
      } catch (err) {
        openTransactionFailureModal("Bill Payment Failed", err.message);
      }
    });
  });
}
