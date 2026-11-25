/** In-memory UI state, formatting helpers, and shared client validators. */

export const appState = {
  user: null,
  accessToken: null,
  dashboard: null,
  banks: [],
  billProviders: null,
  activeView: "dashboard",
  hideBalance: false,
  pendingRegistration: null,
};

export function clearAuthState() {
  appState.user = null;
  appState.accessToken = null;
  appState.dashboard = null;
  appState.banks = [];
  appState.billProviders = null;
}

export function formatNGN(value) {
  const num = Number(value ?? 0);
  return `\u20A6${num.toLocaleString("en-NG", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatDateTime(isoString) {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleString("en-NG", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function newIdempotencyKey(prefix = "bbk") {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `${prefix}_${window.crypto.randomUUID()}`;
  }
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function isValidNigerianPhoneClient(raw) {
  const cleaned = String(raw || "").trim().replace(/[\s\-()]+/g, "");
  if (/^\+2340?(70|80|81|90|91)\d{8}$/.test(cleaned)) return true;
  if (/^2340?(70|80|81|90|91)\d{8}$/.test(cleaned)) return true;
  if (/^0(70|80|81|90|91)\d{8}$/.test(cleaned)) return true;
  if (/^(70|80|81|90|91)\d{8}$/.test(cleaned)) return true;
  return false;
}

export function validatePasswordClient(pw, confirmPw) {
  if (!pw || pw.length < 7) return "Password must be at least 7 characters long.";
  if (!/[^A-Za-z0-9\s]/.test(pw)) return "Password must contain at least one symbol (e.g. !@#$).";
  if (confirmPw !== undefined && pw !== confirmPw) return "Passwords do not match.";
  return null;
}

export function maskEmailClient(email) {
  const clean = String(email || "").trim().toLowerCase();
  if (!clean.includes("@")) return clean;
  const [local, domain] = clean.split("@", 2);
  if (local.length <= 1) return `${local}***@${domain}`;
  if (local.length === 2) return `${local[0]}***${local[1]}@${domain}`;
  return `${local.slice(0, 2)}***${local.slice(-1)}@${domain}`;
}
