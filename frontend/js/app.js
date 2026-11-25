/** Application bootstrap: 3-second BraveBank splash screen, brand SVG hydration, navigation, and session lifecycle. */

import { apiRequest, ensureCsrfToken } from "./api.js";
import { initAuthFlow } from "./auth.js";
import { renderPayments } from "./bills.js";
import { renderCards } from "./cards.js";
import { renderAccountDetails, renderDashboard } from "./dashboard.js";
import {
  initStarfieldBackdrop,
  isSoundMuted,
  toggleSoundMuted,
  unlockAudioOnGesture,
} from "./effects.js";
import { renderHistory } from "./history.js";
import { icon } from "./icons.js";
import { hydrateBrandElements } from "./logo.js";
import { renderNotifications } from "./notifications.js";
import { renderProfile, renderSettings, renderSupport } from "./profile.js";
import { renderSavings } from "./savings.js";
import { appState, clearAuthState, escapeHtml } from "./state.js";
import { renderAddMoney, renderTransfers, renderWithdraw } from "./transfers.js";
import { showToast } from "./ui.js";

const splashScreen = document.getElementById("splash-screen");
const authShell = document.getElementById("auth-shell");
const appShell = document.getElementById("app-shell");
const topUtilityBar = document.getElementById("top-utility-bar");
const sidebar = document.getElementById("sidebar");
const viewRoot = document.getElementById("view-root");
const pageTitle = document.getElementById("page-title");
const pageSubtitle = document.getElementById("page-subtitle");
const notifBadge = document.getElementById("nav-notif-badge");
const topNotifDot = document.getElementById("top-notif-dot");
const topProfileBtn = document.getElementById("top-profile-btn");
const sidebarUserCard = document.getElementById("sidebar-user-card");

let splashTimer = null;
let splashDone = false;

const VIEW_META = {
  dashboard: ["BraveBank", "Banking Without Limits"],
  "add-money": ["Add Money", "Fund your BraveBank NGN account"],
  withdraw: ["Withdraw", "Simulated NGN cash-out"],
  transfers: ["Transfer", "Send money fast & safely"],
  payments: ["Pay Bills", "Airtime, data, electricity, TV & education"],
  savings: ["Savings Vault", "Automated NGN goals & simulated interest"],
  cards: ["Cards Management", "Simulated Verve & Mastercard virtual cards"],
  history: ["Transaction History", "PostgreSQL-backed ledger records"],
  "account-details": ["Account Details", "BraveBank 10-digit NGN account"],
  notifications: ["Notifications Center", "Account & transaction alerts"],
  profile: ["Profile & KYC", "Customer identity and verification status"],
  settings: ["Security & Settings", "4-digit PIN, password, and active sessions"],
  support: ["24/7 Support", "FAQs and support tickets"],
};

// Render declarative BraveBank swoosh stars, wordmarks, watermarks, and ambient starfield
hydrateBrandElements();
initStarfieldBackdrop();
unlockAudioOnGesture();

const topSoundToggleBtn = document.getElementById("top-sound-toggle-btn");
function syncAllSoundButtons() {
  const muted = isSoundMuted();
  if (topSoundToggleBtn) {
    topSoundToggleBtn.innerHTML = muted ? icon("volumeX", 17) : icon("volume2", 17);
    topSoundToggleBtn.setAttribute("aria-label", muted ? "Unmute transaction sounds" : "Mute transaction sounds");
    topSoundToggleBtn.setAttribute("title", muted ? "Sounds Muted (Click to Enable)" : "Sounds On (Click to Mute)");
    topSoundToggleBtn.classList.toggle("is-muted", muted);
  }
  const dashSoundBtn = document.getElementById("dash-sound-btn");
  if (dashSoundBtn) {
    dashSoundBtn.innerHTML = muted ? icon("volumeX", 18) : icon("volume2", 18);
    dashSoundBtn.classList.toggle("is-muted", muted);
    dashSoundBtn.setAttribute("aria-label", muted ? "Unmute transaction sounds" : "Mute transaction sounds");
    dashSoundBtn.setAttribute("title", muted ? "Sounds Muted" : "Sounds On");
  }
  const settingsSoundBtn = document.getElementById("settings-sound-toggle-btn");
  if (settingsSoundBtn) {
    settingsSoundBtn.innerHTML = `${muted ? icon("volumeX", 16) : icon("volume2", 16)} <span>${muted ? "Sounds Muted" : "Sounds Enabled"}</span>`;
  }
}
syncAllSoundButtons();
if (topSoundToggleBtn) {
  topSoundToggleBtn.addEventListener("click", () => {
    const muted = toggleSoundMuted();
    showToast(muted ? "Transaction sounds muted." : "Transaction sounds enabled.", "info");
  });
}
window.addEventListener("bravebank:sound-pref-changed", syncAllSoundButtons);

function dismissSplash() {
  if (splashDone) return;
  splashDone = true;
  if (splashTimer) {
    clearTimeout(splashTimer);
    splashTimer = null;
  }
  if (splashScreen) {
    splashScreen.classList.add("fade-out");
    setTimeout(() => {
      splashScreen.classList.add("hidden");
    }, 450);
  }
}

function updateUserChrome() {
  if (!appState.user) return;
  const initials = `${appState.user.first_name[0] || "B"}${appState.user.surname[0] || "B"}`.toUpperCase();
  topProfileBtn.textContent = initials;
  sidebarUserCard.innerHTML = `
    <strong>${escapeHtml(appState.user.first_name)} ${escapeHtml(appState.user.surname)}</strong>
    <span>${escapeHtml(appState.user.phone_number)}</span><br/>
    <span>Acct: ${escapeHtml(appState.user.account_number || "—")}</span>
  `;
}

function updateNotifBadge(count) {
  if (count > 0) {
    notifBadge.textContent = String(count);
    notifBadge.classList.remove("hidden");
    topNotifDot.textContent = count > 99 ? "99+" : String(count);
    topNotifDot.classList.remove("hidden");
  } else {
    notifBadge.classList.add("hidden");
    topNotifDot.classList.add("hidden");
  }
}

async function navigate(rawView) {
  const [viewName, subArg] = String(rawView || "dashboard").split(":");
  appState.activeView = viewName;
  sidebar.classList.remove("open");

  if (topUtilityBar) {
    topUtilityBar.classList.toggle("mobile-dash-hidden", viewName === "dashboard");
  }

  document.querySelectorAll(".nav-item, .bottom-nav-btn").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewName);
  });

  const [title, sub] = VIEW_META[viewName] || ["BraveBank", ""];
  pageTitle.textContent = title;
  pageSubtitle.textContent = sub;

  viewRoot.innerHTML = `<div class="card empty-state">Loading ${escapeHtml(title)}...</div>`;

  try {
    if (viewName === "dashboard") {
      await renderDashboard(viewRoot, navigate, updateNotifBadge);
    } else if (viewName === "add-money") {
      await renderAddMoney(viewRoot, navigate);
    } else if (viewName === "withdraw") {
      await renderWithdraw(viewRoot, navigate);
    } else if (viewName === "transfers") {
      await renderTransfers(viewRoot, navigate);
    } else if (viewName === "payments") {
      await renderPayments(viewRoot, navigate, subArg || "airtime");
    } else if (viewName === "savings") {
      await renderSavings(viewRoot, navigate);
    } else if (viewName === "cards") {
      await renderCards(viewRoot, navigate);
    } else if (viewName === "history") {
      await renderHistory(viewRoot, navigate);
    } else if (viewName === "account-details") {
      await renderAccountDetails(viewRoot, navigate);
    } else if (viewName === "notifications") {
      await renderNotifications(viewRoot, navigate, updateNotifBadge);
    } else if (viewName === "profile") {
      await renderProfile(viewRoot, navigate, updateUserChrome, performLogout);
    } else if (viewName === "settings") {
      await renderSettings(viewRoot, navigate, updateUserChrome);
    } else if (viewName === "support") {
      await renderSupport(viewRoot, navigate);
    }
  } catch (err) {
    viewRoot.innerHTML = `<div class="card empty-state" style="color:var(--danger);">${escapeHtml(err.message)}</div>`;
    showToast(err.message, "error");
  }
}

async function enterAuthenticatedShell() {
  if (!appState.user) {
    appState.user = await apiRequest("/api/auth/me");
  }
  if (!appState.accessToken && !appState.csrfToken) {
    await ensureCsrfToken();
  }
  updateUserChrome();
  authShell.classList.add("hidden");
  appShell.classList.remove("hidden");
  await navigate("dashboard");
}

const { showAuthScreen } = initAuthFlow({ enterAuthenticatedShell });

function exitToAuthShell(screen = "welcome") {
  clearAuthState();
  appShell.classList.add("hidden");
  authShell.classList.remove("hidden");
  showAuthScreen(screen);
}

async function performLogout() {
  try {
    await apiRequest(
      "/api/auth/logout",
      { method: "POST", suppressSessionExpired: true },
      true
    );
  } catch {
    // Ensure local state resets cleanly even if session already expired
  }
  appState.pendingRegistration = null;
  const loginPwEl = document.getElementById("login-password");
  if (loginPwEl) loginPwEl.value = "";
  exitToAuthShell("login");
  showToast("Logged out securely.", "info");
}

// App navigation & logout listeners
document.querySelectorAll("[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => navigate(btn.dataset.view));
});
document.getElementById("top-notif-btn").addEventListener("click", () => navigate("notifications"));
document.getElementById("top-profile-btn").addEventListener("click", () => navigate("profile"));
document.getElementById("open-sidebar-btn").addEventListener("click", () => sidebar.classList.add("open"));
document.getElementById("close-sidebar-btn").addEventListener("click", () => sidebar.classList.remove("open"));
document.getElementById("logout-btn").addEventListener("click", performLogout);
document.getElementById("top-logout-btn").addEventListener("click", performLogout);

window.addEventListener("bravebank:session-expired", () => {
  exitToAuthShell("login");
  showToast("Your session expired. Please login again.", "error");
});

// Run 3-second splash screen alongside backend /api/auth/me session check
let initialUser = null;
const authCheckPromise = apiRequest("/api/auth/me", {}, true)
  .then((user) => {
    initialUser = user;
  })
  .catch(() => {
    initialUser = null;
  });

async function finishIntro() {
  dismissSplash();
  await authCheckPromise;
  if (initialUser) {
    appState.user = initialUser;
    await enterAuthenticatedShell();
  } else {
    exitToAuthShell("welcome");
  }
}

splashTimer = setTimeout(finishIntro, 3000);
if (splashScreen) {
  const skipBtn = document.getElementById("splash-skip-btn");
  if (skipBtn) {
    skipBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      finishIntro();
    });
  }
}
