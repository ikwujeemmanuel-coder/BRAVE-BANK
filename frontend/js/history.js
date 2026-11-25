/** Transaction History screen with inflow/outflow filter, search, and detail receipts. */

import { apiRequest } from "./api.js";
import { icon } from "./icons.js";
import { renderTransactionCards, wireTransactionClicks } from "./transfers.js";

export async function renderHistory(root, navigate) {
  let direction = "";

  root.innerHTML = `
    <section class="card">
      <div class="section-header">
        <div style="display:flex; align-items:center; gap:10px;">
          <button type="button" class="back-arrow-btn" id="hist-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
          <h3 style="margin:0;">Transaction History</h3>
        </div>
        <div class="segmented">
          <button type="button" class="seg-btn active" data-hdir="">All</button>
          <button type="button" class="seg-btn" data-hdir="credit">Inflow</button>
          <button type="button" class="seg-btn" data-hdir="debit">Outflow</button>
        </div>
      </div>
      <form id="tx-filter-form" class="filter-bar">
        <input id="tx-search" type="text" placeholder="Search reference, narration, or recipient..." />
        <select id="tx-category">
          <option value="">All Categories</option>
          <option value="demo_funding">Demo Funding</option>
          <option value="deposit">Deposit</option>
          <option value="withdrawal">Withdrawal</option>
          <option value="internal_transfer">Internal Transfer</option>
          <option value="external_transfer">External Transfer</option>
          <option value="savings_contribution">Savings Contribution</option>
          <option value="bill_payment">Bill Payment</option>
        </select>
        <button type="submit" class="btn btn-primary btn-pill">Search</button>
      </form>
      <div id="history-list-wrap"></div>
    </section>
  `;

  async function loadRows() {
    const params = new URLSearchParams();
    const search = document.getElementById("tx-search").value.trim();
    const category = document.getElementById("tx-category").value;
    if (search) params.set("search", search);
    if (category) params.set("category", category);
    if (direction) params.set("direction", direction);

    const data = await apiRequest(`/api/transactions?${params.toString()}`);
    const wrap = document.getElementById("history-list-wrap");
    wrap.innerHTML = renderTransactionCards(data.items);
    wireTransactionClicks(wrap);
  }

  document.getElementById("hist-back-btn").addEventListener("click", () => navigate("dashboard"));

  root.querySelectorAll("[data-hdir]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      direction = btn.dataset.hdir;
      root.querySelectorAll("[data-hdir]").forEach((b) => b.classList.toggle("active", b === btn));
      await loadRows();
    });
  });

  document.getElementById("tx-filter-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await loadRows();
  });

  await loadRows();
}
