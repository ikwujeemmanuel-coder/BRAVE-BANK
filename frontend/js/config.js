/**
 * Centralized API environment configuration for BRAVEBANK.
 *
 * Maintenance:
 * - Production Static Site (https://bravebank-frontend.onrender.com) routes all
 *   API requests to the deployed Render Web Service (https://brave-bank.onrender.com).
 * - Local FastAPI full-stack dev (http://localhost:3000 or http://127.0.0.1:3000)
 *   and same-origin backend previews use relative "" base paths.
 * - Optional runtime override can be supplied via window.__BRAVEBANK_CONFIG__.API_BASE_URL
 *   or <meta name="bravebank-api-base" content="https://..."> without editing source modules.
 */

export const PRODUCTION_BACKEND_URL = "https://brave-bank.onrender.com";

const SAME_ORIGIN_HOSTS = new Set(["brave-bank.onrender.com"]);
const LOCAL_DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);
const LOCAL_BACKEND_PORTS = new Set(["3000", "8000"]);

function sanitizeBaseUrl(rawUrl) {
  const trimmed = String(rawUrl || "").trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol === "https:" || (parsed.protocol === "http:" && LOCAL_DEV_HOSTS.has(parsed.hostname))) {
      return parsed.origin;
    }
  } catch {
    // Ignore invalid override URLs and fall back to automatic resolution
  }
  return "";
}

export function resolveApiBaseUrl() {
  if (typeof window !== "undefined") {
    const runtimeOverride = window.__BRAVEBANK_CONFIG__?.API_BASE_URL;
    const sanitizedRuntime = sanitizeBaseUrl(runtimeOverride);
    if (sanitizedRuntime) return sanitizedRuntime;
  }

  if (typeof document !== "undefined") {
    const metaTag = document.querySelector('meta[name="bravebank-api-base"]');
    const sanitizedMeta = sanitizeBaseUrl(metaTag?.getAttribute("content"));
    if (sanitizedMeta) return sanitizedMeta;
  }

  if (typeof window === "undefined" || !window.location) {
    return PRODUCTION_BACKEND_URL;
  }

  const { hostname, port, protocol } = window.location;

  if (protocol === "file:") {
    return "http://127.0.0.1:3000";
  }

  if (LOCAL_DEV_HOSTS.has(hostname)) {
    return LOCAL_BACKEND_PORTS.has(port) ? "" : `http://${hostname}:3000`;
  }

  if (SAME_ORIGIN_HOSTS.has(hostname) || hostname.endsWith(".run.app")) {
    return "";
  }

  // Render Static Site (https://bravebank-frontend.onrender.com) and any other
  // standalone frontend host always target the dedicated Render backend service.
  return PRODUCTION_BACKEND_URL;
}

export const API_BASE_URL = resolveApiBaseUrl();

/**
 * Resolves a backend API path (for example "/api/auth/login" or "/api/transactions?type=debit")
 * against the centralized API base URL without duplicating slashes or dropping query strings.
 */
export function buildApiUrl(path) {
  const raw = String(path || "").trim();
  if (!raw.startsWith("/") || raw.startsWith("//")) {
    throw new Error(`Invalid relative API path: ${raw}`);
  }
  return API_BASE_URL ? `${API_BASE_URL}${raw}` : raw;
}
