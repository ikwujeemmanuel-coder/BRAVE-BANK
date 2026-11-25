/** Cookie + CSRF HTTP client communicating with the FastAPI backend. */

import { appState, clearAuthState } from "./state.js";

let refreshPromise = null;

function readCookie(name) {
  const prefix = `${name}=`;
  const parts = document.cookie.split(";");
  for (const part of parts) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return "";
}

async function attemptCookieRefresh() {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({}),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json();
        appState.user = data.user;
        if (data.access_token) {
          appState.accessToken = data.access_token;
        }
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function apiRequest(path, options = {}, retryOn401 = true) {
  const method = (options.method || "GET").toUpperCase();
  const headers = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    ...(options.headers || {}),
  };

  if (appState.accessToken && !headers.Authorization) {
    headers.Authorization = `Bearer ${appState.accessToken}`;
  }

  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCookie("bb_csrf_token");
    if (csrf) {
      headers["X-CSRF-Token"] = csrf;
    }
  }

  const response = await fetch(path, {
    ...options,
    method,
    credentials: "same-origin",
    headers,
  });

  if (
    response.status === 401 &&
    retryOn401 &&
    !path.startsWith("/api/auth/login") &&
    !path.startsWith("/api/auth/refresh") &&
    !path.startsWith("/api/auth/register") &&
    !path.startsWith("/api/auth/otp")
  ) {
    const refreshed = await attemptCookieRefresh();
    if (refreshed) {
      return apiRequest(path, options, false);
    }
    if (appState.user || appState.accessToken) {
      clearAuthState();
      window.dispatchEvent(new CustomEvent("bravebank:session-expired"));
    }
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg || String(item)).join("; ")
      : data.detail || `Request failed (${response.status})`;
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }
  return data;
}
