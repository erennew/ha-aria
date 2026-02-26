/**
 * API client for ARIA.
 *
 * - baseUrl derived from window.location.origin
 * - fetchJson() wrapper with error handling
 * - Request deduplication: concurrent fetches to the same path share one promise
 * - X-API-Key injected from window.__ARIA_CONFIG__.apiKey when present (#267)
 */

// Derive base URL from pathname to support both direct (:8001) and proxied (/aria) access.
// At :8001/ui/  → pathname '/ui/'  → prefix '' → baseUrl 'https://host:8001'
// At /aria/ui/  → pathname '/aria/ui/' → prefix '/aria' → baseUrl 'https://host/aria'
const pathPrefix = window.location.pathname.replace(/\/ui(\/.*)?$/, '');
const baseUrl = window.location.origin + pathPrefix;

/**
 * Resolve the API key for authenticated requests (#267).
 *
 * Resolution order:
 *  1. window.__ARIA_CONFIG__.apiKey  — injected by backend HTML template
 *  2. localStorage item 'aria_api_key' — user-configurable fallback
 *
 * Returns null when no key is configured (auth disabled).
 */
function getApiKey() {
  return (
    window.__ARIA_CONFIG__?.apiKey ||
    localStorage.getItem('aria_api_key') ||
    null
  );
}

/**
 * Build auth headers. Returns { 'X-API-Key': key } when a key is configured,
 * otherwise returns an empty object.
 */
function authHeaders() {
  const key = getApiKey();
  return key ? { 'X-API-Key': key } : {};
}

/** In-flight request map for deduplication. Key = path, value = pending Promise. */
const inflight = new Map();

/**
 * Fetch JSON from the hub API. Throws on non-200 responses.
 * Concurrent calls to the same path return the same promise (dedup).
 *
 * @param {string} path - API path (e.g. "/api/cache/entities")
 * @returns {Promise<any>} Parsed JSON response
 */
export function fetchJson(path) {
  if (inflight.has(path)) {
    return inflight.get(path);
  }

  const promise = fetch(`${baseUrl}${path}`, { headers: authHeaders() })
    .then((res) => {
      if (!res.ok) {
        const err = new Error(`HTTP ${res.status}: ${res.statusText}`);
        err.status = res.status;
        throw err;
      }
      return res.json();
    })
    .finally(() => {
      inflight.delete(path);
    });

  inflight.set(path, promise);
  return promise;
}

/**
 * PUT JSON to the hub API.
 * @param {string} path - API path
 * @param {any} body - Request body (will be JSON.stringify'd)
 * @returns {Promise<any>} Parsed JSON response
 */
export function putJson(path, body) {
  return fetch(`${baseUrl}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  }).then((res) => {
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return res.json();
  });
}

/**
 * POST JSON to the hub API.
 * @param {string} path - API path
 * @param {any} body - Request body (will be JSON.stringify'd)
 * @returns {Promise<any>} Parsed JSON response
 */
export function postJson(path, body) {
  return fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  }).then((res) => {
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return res.json();
  });
}

/**
 * Fetch JSON with silent 404 handling — use for dashboard data that may not exist yet.
 * Non-404 errors are logged to console.
 *
 * @param {string} url - API path
 * @param {function} setter - State setter to call with the result
 */
export function safeFetch(url, setter) {
  return fetchJson(url)
    .then(setter)
    .catch(err => {
      if (err?.status !== 404) console.error(`Failed to fetch ${url}:`, err);
      return { error: true, status: err?.status, message: err?.message ?? err?.statusText };
    });
}

export const EMPTY_CAPABILITIES = { capabilities: {}, entities: {}, devices: {} };
export const EMPTY_INTELLIGENCE = { predictions: [], anomalies: [], correlations: [] };
export const EMPTY_EVENTS = { events: [], total: 0 };

export const API_BASE = baseUrl;

export { baseUrl };
