/** Centralized cross-origin cookie + Bearer + CSRF HTTP client for BRAVEBANK. */

import { buildApiUrl } from "./config.js";
import { appState, clearAuthState } from "./state.js";

let refreshPromise = null;
let csrfPromise = null;

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function isRefreshExcludedPath(path) {
  return (
    path.startsWith("/api/auth/login") ||
    path.startsWith("/api/auth/refresh") ||
    path.startsWith("/api/auth/register") ||
    path.startsWith("/api/auth/otp") ||
    path.startsWith("/api/auth/password/reset") ||
    path.startsWith("/api/auth/csrf")
  );
}

function isPublicAuthPostPath(path) {
  return (
    path.startsWith("/api/auth/login") ||
    path.startsWith("/api/auth/register") ||
    path.startsWith("/api/auth/otp") ||
    path.startsWith("/api/auth/password/reset") ||
    path.startsWith("/api/auth/refresh")
  );
}

function readCookie(name) {
  if (typeof document === "undefined") return "";
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

function isTokenUsable(token) {
  if (!token || typeof token !== "string") return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const payload = JSON.parse(atob(padded));
    if (typeof payload.exp !== "number") return true;
    return payload.exp * 1000 > Date.now() + 5000;
  } catch {
    return false;
  }
}

export async function ensureCsrfToken(forceRefresh = false) {
  if (!forceRefresh) {
    if (appState.csrfToken) return appState.csrfToken;
    const sameOriginCookie = readCookie("bb_csrf_token");
    if (sameOriginCookie) {
      appState.csrfToken = sameOriginCookie;
      return sameOriginCookie;
    }
  }

  if (!csrfPromise) {
    csrfPromise = fetch(buildApiUrl("/api/auth/csrf"), {
      method: "GET",
      credentials: "include",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then(async (res) => {
        if (!res.ok) return "";
        const data = await res.json().catch(() => ({}));
        const token = data.csrf_token || readCookie("bb_csrf_token") || "";
        if (token) {
          appState.csrfToken = token;
        }
        return token;
      })
      .catch(() => "")
      .finally(() => {
        csrfPromise = null;
      });
  }

  return csrfPromise;
}

async function attemptCookieRefresh() {
  if (!refreshPromise) {
    const headers = {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    };
    const knownCsrf = appState.csrfToken || readCookie("bb_csrf_token");
    if (knownCsrf) {
      headers["X-CSRF-Token"] = knownCsrf;
    }

    refreshPromise = fetch(buildApiUrl("/api/auth/refresh"), {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify({}),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json().catch(() => null);
        if (!data || !data.user) return false;
        appState.user = data.user;
        appState.accessToken = data.access_token || null;
        if (data.csrf_token) {
          appState.csrfToken = data.csrf_token;
        } else {
          const cookieCsrf = readCookie("bb_csrf_token");
          if (cookieCsrf) appState.csrfToken = cookieCsrf;
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

function isBinaryOrFormBody(body) {
  if (body === undefined || body === null) return false;
  if (typeof FormData !== "undefined" && body instanceof FormData) return true;
  if (typeof Blob !== "undefined" && body instanceof Blob) return true;
  if (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams) return true;
  if (typeof ArrayBuffer !== "undefined" && (body instanceof ArrayBuffer || ArrayBuffer.isView(body))) {
    return true;
  }
  return false;
}

async function parseResponsePayload(response) {
  if (response.status === 204) return {};
  const contentLength = response.headers.get("content-length");
  if (contentLength === "0") return {};

  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  const text = await response.text().catch(() => "");
  if (!text || !text.trim()) return {};

  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(text);
    } catch {
      return { rawText: text };
    }
  }

  try {
    return JSON.parse(text);
  } catch {
    return { rawText: text };
  }
}

export async function apiRequest(path, options = {}, retryOn401 = true) {
  const { suppressSessionExpired = false, headers: customHeaders = {}, ...fetchOptions } = options;
  const method = (fetchOptions.method || "GET").toUpperCase();
  const url = buildApiUrl(path);

  // Detect expired in-memory Bearer token proactively before sending authenticated requests
  if (appState.accessToken && !isTokenUsable(appState.accessToken)) {
    appState.accessToken = null;
    if (retryOn401 && !isRefreshExcludedPath(path) && appState.user) {
      const refreshed = await attemptCookieRefresh();
      if (!refreshed) {
        clearAuthState();
        if (!suppressSessionExpired) {
          window.dispatchEvent(new CustomEvent("bravebank:session-expired"));
        }
        const expiredErr = new Error("Session expired. Please sign in again.");
        expiredErr.status = 401;
        throw expiredErr;
      }
    }
  }

  const headers = {
    "X-Requested-With": "XMLHttpRequest",
    ...customHeaders,
  };

  const hasContentType = Object.keys(headers).some((k) => k.toLowerCase() === "content-type");
  if (!hasContentType && fetchOptions.body !== undefined && !isBinaryOrFormBody(fetchOptions.body)) {
    headers["Content-Type"] = "application/json";
  }

  const hasExplicitAuth = Object.keys(headers).some((k) => k.toLowerCase() === "authorization");
  if (!hasExplicitAuth && isTokenUsable(appState.accessToken)) {
    headers.Authorization = `Bearer ${appState.accessToken}`;
  }

  const isCookieAuthenticatedUnsafe = !SAFE_METHODS.has(method) && !headers.Authorization;
  if (isCookieAuthenticatedUnsafe && !path.startsWith("/api/auth/csrf")) {
    let csrf = appState.csrfToken || readCookie("bb_csrf_token");
    if (!csrf && !isPublicAuthPostPath(path)) {
      csrf = await ensureCsrfToken();
    }
    if (csrf && !headers["X-CSRF-Token"]) {
      headers["X-CSRF-Token"] = csrf;
    }
  }

  let response;
  try {
    response = await fetch(url, {
      ...fetchOptions,
      method,
      credentials: "include",
      headers,
    });
  } catch (networkErr) {
    const err = new Error(
      "Unable to reach BraveBank server. Check your internet connection or cross-origin settings."
    );
    err.status = 0;
    err.cause = networkErr;
    throw err;
  }

  if (response.status === 401 && retryOn401 && !isRefreshExcludedPath(path)) {
    const refreshed = await attemptCookieRefresh();
    if (refreshed) {
      return apiRequest(path, options, false);
    }
    if (appState.user || appState.accessToken) {
      clearAuthState();
      if (!suppressSessionExpired) {
        window.dispatchEvent(new CustomEvent("bravebank:session-expired"));
      }
    }
  }

  const data = await parseResponsePayload(response);
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg || String(item)).join("; ")
      : data.detail ||
        (data.rawText ? data.rawText.slice(0, 180) : "") ||
        `Request failed (${response.status})`;
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }
  return data;
}
