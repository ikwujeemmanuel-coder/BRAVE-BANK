/** Notifications Center screen with read state syncing. */

import { apiRequest } from "./api.js";
import { icon } from "./icons.js";
import { escapeHtml, formatDateTime } from "./state.js";
import { showToast } from "./ui.js";

export async function renderNotifications(root, navigate, refreshChrome) {
  const items = await apiRequest("/api/notifications");
  const unread = items.filter((n) => !n.is_read).length;
  refreshChrome(unread);

  root.innerHTML = `
    <section class="card">
      <div class="section-header">
        <div style="display:flex; align-items:center; gap:10px;">
          <button type="button" class="back-arrow-btn" id="notif-back-btn" aria-label="Back to Home">${icon("arrowLeft", 20)}</button>
          <h3 style="margin:0;">Notifications (${unread} unread)</h3>
        </div>
        <button id="mark-all-read-btn" type="button" class="btn btn-outline-blue btn-sm">Mark All Read</button>
      </div>
      <div class="form-stack">
        ${
          items.length
            ? items
                .map(
                  (n) => `
              <div class="tx-row-item" style="background:${n.is_read ? "#fff" : "#eff6ff"}; cursor:default;">
                <div class="tx-left">
                  <div class="tx-icon-circle ${n.is_read ? "debit" : "credit"}">${icon("bell", 18)}</div>
                  <div>
                    <strong>${escapeHtml(n.title)}</strong>
                    <p style="margin:2px 0; font-size:0.86rem; color:var(--muted);">${escapeHtml(n.message)}</p>
                    <small style="color:var(--muted);">${escapeHtml(formatDateTime(n.created_at))}</small>
                  </div>
                </div>
                ${
                  n.is_read
                    ? `<span class="status-tag">Read</span>`
                    : `<button type="button" class="btn btn-outline-blue btn-sm" data-read-notif="${escapeHtml(n.id)}">Read</button>`
                }
              </div>`
                )
                .join("")
            : `<div class="empty-state">No notifications yet.</div>`
        }
      </div>
    </section>
  `;

  document.getElementById("notif-back-btn").addEventListener("click", () => navigate("dashboard"));
  document.getElementById("mark-all-read-btn").addEventListener("click", async () => {
    await apiRequest("/api/notifications/read-all", { method: "POST" });
    showToast("All notifications marked as read.", "success");
    await renderNotifications(root, navigate, refreshChrome);
  });

  root.querySelectorAll("[data-read-notif]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiRequest(`/api/notifications/${btn.dataset.readNotif}/read`, { method: "POST" });
      await renderNotifications(root, navigate, refreshChrome);
    });
  });
}
