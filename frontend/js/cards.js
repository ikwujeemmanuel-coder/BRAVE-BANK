/** Virtual NGN Verve & Mastercard Cards Management screen. */

import { apiRequest } from "./api.js";
import { icon } from "./icons.js";
import { escapeHtml, formatNGN } from "./state.js";
import { showToast } from "./ui.js";

export async function renderCards(root, navigate) {
  const cards = await apiRequest("/api/cards");
  let filter = "all";

  function draw() {
    const filtered = cards.filter((c) => (filter === "all" ? true : c.status === filter));
    root.innerHTML = `
      <div class="card">
        <div class="section-header" style="margin-bottom:0;">
          <div style="display:flex; align-items:center; gap:10px;">
            <button type="button" class="back-arrow-btn" id="cards-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
            <h3 style="margin:0;">Cards Management</h3>
          </div>
          <div class="segmented">
            <button type="button" class="seg-btn ${filter === "all" ? "active" : ""}" data-cfilter="all">All</button>
            <button type="button" class="seg-btn ${filter === "active" ? "active" : ""}" data-cfilter="active">Active</button>
            <button type="button" class="seg-btn ${filter === "frozen" ? "active" : ""}" data-cfilter="frozen">Frozen</button>
          </div>
        </div>
      </div>

      <div class="grid-2">
        <section class="card form-stack">
          <h3>Issue Virtual Card (Simulated)</h3>
          <form id="create-card-form" class="form-stack">
            <label class="field">
              <span>Card Label</span>
              <input id="card-label" type="text" required minlength="2" placeholder="Online Payments Card" />
            </label>
            <label class="field">
              <span>Network</span>
              <select id="card-brand">
                <option value="Verve">Verve (NGN)</option>
                <option value="Mastercard">Mastercard (NGN)</option>
              </select>
            </label>
            <label class="field">
              <span>Monthly Limit (NGN)</span>
              <input id="card-limit" type="number" step="0.01" min="1000" value="500000" required />
            </label>
            <button type="submit" class="btn btn-primary btn-pill">Create Virtual Card</button>
          </form>
        </section>

        <section class="form-stack">
          ${
            filtered.length
              ? filtered
                  .map(
                    (c) => `
                <div class="card form-stack">
                  <div class="stitch-card-visual ${c.status === "frozen" ? "frozen" : ""}">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                      <strong>BraveBank &middot; ${escapeHtml(c.brand)}</strong>
                      <span class="status-tag ${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
                    </div>
                    <div class="card-pan">${escapeHtml(c.masked_pan)}</div>
                    <div style="display:flex; justify-content:space-between; font-size:0.82rem;">
                      <span>${escapeHtml(c.label)}</span>
                      <span>EXP ${escapeHtml(c.expiry)}</span>
                    </div>
                  </div>
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <small style="color:var(--muted);">Spending Limit: ${formatNGN(c.spending_limit)}</small>
                    <button type="button" class="btn btn-outline-blue btn-sm" data-toggle-card="${escapeHtml(c.id)}">
                      ${c.status === "active" ? "Freeze Card" : "Unfreeze Card"}
                    </button>
                  </div>
                </div>`
                  )
                  .join("")
              : `<div class="card empty-state">No virtual cards in this view.</div>`
          }
        </section>
      </div>
    `;

    document.getElementById("cards-back-btn").addEventListener("click", () => navigate("dashboard"));

    root.querySelectorAll("[data-cfilter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        filter = btn.dataset.cfilter;
        draw();
      });
    });

    document.getElementById("create-card-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await apiRequest("/api/cards", {
          method: "POST",
          body: JSON.stringify({
            label: document.getElementById("card-label").value,
            brand: document.getElementById("card-brand").value,
            spending_limit: document.getElementById("card-limit").value,
          }),
        });
        showToast("Simulated virtual card issued.", "success");
        await renderCards(root, navigate);
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    root.querySelectorAll("[data-toggle-card]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const res = await apiRequest(`/api/cards/${btn.dataset.toggleCard}/toggle-freeze`, {
          method: "POST",
        });
        showToast(`Card is now ${res.status}.`, "success");
        await renderCards(root, navigate);
      });
    });
  }

  draw();
}
