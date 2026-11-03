/**
 * Single HTTP client for the DRRAS service.
 * Every call is same-origin, credentials included, and errors arrive as one
 * consistent ApiError shape so the UI can render useful messages.
 */

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

let csrfToken = null;
let bearerToken = null;
let onUnauthorized = null;

export function setCsrf(token) {
  csrfToken = token || null;
}

export function setBearer(token) {
  bearerToken = token || null;
}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

async function request(method, path, body, options = {}) {
  const headers = { Accept: "application/json" };
  const init = {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers,
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (csrfToken && options.csrf !== false) headers["X-CSRF-Token"] = csrfToken;
  if (bearerToken) headers.Authorization = `Bearer ${bearerToken}`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeout ?? 25000);
  init.signal = controller.signal;

  let response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    clearTimeout(timeout);
    if (error?.name === "AbortError") {
      throw new ApiError("The server took too long to respond. Please try again.", 0);
    }
    throw new ApiError(
      "The DRRAS service could not be reached. Check that the backend is running, then reload.",
      0,
    );
  }
  clearTimeout(timeout);

  let payload = null;
  const text = await response.text().catch(() => "");
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const message =
      payload?.error ||
      (response.status === 401
        ? "Your session has expired. Sign in again."
        : `The request failed (${response.status}).`);
    if (response.status === 401 && typeof onUnauthorized === "function" && options.redirect !== false) {
      onUnauthorized(message);
    }
    throw new ApiError(message, response.status, payload);
  }
  return payload ?? {};
}

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request("GET", "/api/health"),
  overview: () => request("GET", "/api/overview"),
  helpCentres: () => request("GET", "/api/help-centres"),
  nearby: (params) => request("GET", `/api/nearby${query(params)}`),
  places: (q) => request("GET", `/api/places${query({ q })}`),
  route: (fromLat, fromLon, toLat, toLon) =>
    request("GET", `/api/route${query({ fromLat, fromLon, toLat, toLon })}`),
  inventory: () => request("GET", "/api/inventory"),
  submitRequest: (payload) => request("POST", "/api/requests", payload, { timeout: 30000 }),
  uploadEvidence: (payload) => request("POST", "/api/uploads", payload, { timeout: 45000 }),
  requestStatus: (id) => request("GET", `/api/requests/${encodeURIComponent(id)}`, undefined, { redirect: false }),

  login: (password) =>
    request("POST", "/api/admin/login", { password }, { csrf: false, redirect: false }),
  logout: () => request("POST", "/api/admin/logout", {}, { timeout: 10000 }),
  session: () => request("GET", "/api/admin/session", undefined, { redirect: false }),

  adminRequests: () => request("GET", "/api/admin/requests"),
  adminRequest: (id) => request("GET", `/api/admin/requests/${encodeURIComponent(id)}`),
  adminStats: () => request("GET", "/api/admin/stats"),
  adminAudit: (params = {}) => request("GET", `/api/admin/audit${query(params)}`),
  adminNotifications: () => request("GET", "/api/admin/notifications"),
  adminAllocations: () => request("GET", "/api/admin/allocations"),
  adminCentres: () => request("GET", "/api/admin/help-centres"),
  adminSettings: () => request("GET", "/api/admin/settings"),
  adminInventory: () => request("GET", "/api/admin/inventory"),

  action: (id, payload) =>
    request("POST", `/api/admin/requests/${encodeURIComponent(id)}/action`, payload),
  recommendations: (id) =>
    request("GET", `/api/admin/requests/${encodeURIComponent(id)}/recommendations`),
  allocate: (id, payload) =>
    request("POST", `/api/admin/requests/${encodeURIComponent(id)}/allocations`, payload),
  updateAllocation: (id, payload) =>
    request("PATCH", `/api/admin/allocations/${encodeURIComponent(id)}`, payload),
  updateSettings: (payload) => request("PUT", "/api/admin/settings", payload),
  updateInventory: (payload) => request("PUT", "/api/admin/inventory", payload),
  updateCentre: (id, payload) =>
    request("PATCH", `/api/admin/help-centres/${encodeURIComponent(id)}`, payload),
  createCentre: (payload) => request("POST", "/api/admin/help-centres", payload),
  seedDemo: () => request("POST", "/api/admin/seed-demo", {}),
};
