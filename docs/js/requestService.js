// Single request store for both deployments.
//
// With the Python service running, everything goes through /api and the SQLite
// database: requests are shared between visitors and admin decisions are real.
// On a static host (GitHub Pages) there is no server, so this falls back to
// browser storage and a cosmetic sign-in.
//
// The fallback is explicitly NOT access control. A check the browser can perform
// is a check a visitor can read, and localStorage is per-browser, so an admin on
// Pages sees only requests submitted from that same browser. Run the service
// (see README "Deployment") for anything real.

export const config = {
  // Empty = same origin, which is what the relative /api calls assume.
  // Set to e.g. "https://drras-on-render.fly.dev" to host the API elsewhere and
  // serve only the dashboard from Pages.
  apiBase: "",
  // Flip to false to hard-fail instead of degrading to browser storage.
  allowDemoFallback: true,
  // Cosmetic gate for static hosting only, and readable in the page source by
  // anyone. Use a throwaway value: never the real password you set with
  // --set-password, or publishing this file publishes that credential.
  demoPassphrase: "demo-mode",
};

const DEMO_REQUESTS_KEY = "drras_requests";
const DEMO_SESSION_KEY = "drras_demo_admin";
const PROBE_TIMEOUT_MS = 2000;

const DISASTER_TYPES = ["FLOOD", "EARTHQUAKE", "FIRE", "LANDSLIDE", "INDUSTRIAL_ACCIDENT", "OTHER"];
const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const RESOURCE_CATEGORIES = ["Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply"];

export class ServiceError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ServiceError";
    this.status = status;
  }
}

// localStorage when present, otherwise an in-memory map so this module is
// testable outside a browser. Same key names either way.
const memoryStore = new Map();
function storage() {
  const ls = typeof globalThis !== "undefined" ? globalThis.localStorage : null;
  if (ls) return ls;
  return {
    getItem: (k) => (memoryStore.has(k) ? memoryStore.get(k) : null),
    setItem: (k, v) => memoryStore.set(k, String(v)),
    removeItem: (k) => memoryStore.delete(k),
  };
}

// sessionStorage mirrors "signed in for this tab only"; in-memory fallback keeps
// the module usable where no web storage exists.
const memorySession = new Map();
function session() {
  const ss = typeof globalThis !== "undefined" ? globalThis.sessionStorage : null;
  if (ss) return ss;
  return {
    getItem: (k) => (memorySession.has(k) ? memorySession.get(k) : null),
    setItem: (k, v) => memorySession.set(k, String(v)),
    removeItem: (k) => memorySession.delete(k),
  };
}

function readDemoRequests() {
  try {
    const raw = storage().getItem(DEMO_REQUESTS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeDemoRequests(rows) {
  try {
    storage().setItem(DEMO_REQUESTS_KEY, JSON.stringify(rows));
  } catch (err) {
    throw new ServiceError(`This browser could not save the request (${err?.name || "error"}).`, 500);
  }
}

function newRequestId() {
  const bytes = new Uint8Array(4);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 4; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  return `REQ-${[...bytes].map((b) => b.toString(16).padStart(2, "0").toUpperCase()).join("")}`;
}

/** Mirrors validate_request_payload() in backend/admin_server.py closely enough
 *  that a static demo rejects the same bad input the server would. The server
 *  stays authoritative whenever it is reachable. */
export function validateRequestPayload(raw) {
  if (!raw || typeof raw !== "object") throw new ServiceError("Expected a JSON object.");

  const type = String(raw.type ?? "").trim().toUpperCase();
  if (!DISASTER_TYPES.includes(type)) throw new ServiceError("Unknown disaster type.");

  const severity = String(raw.severity ?? "").trim().toUpperCase();
  if (!SEVERITIES.includes(severity)) throw new ServiceError("Severity must be CRITICAL, HIGH, MEDIUM or LOW.");

  const affected = Number(raw.affectedPeople);
  if (!Number.isFinite(affected) || affected < 0) throw new ServiceError("Affected people must be a number of 0 or more.");

  const locationName = String(raw.locationName ?? "").trim();
  if (!locationName) throw new ServiceError("Location name is required.");
  if (locationName.length > 200) throw new ServiceError("Location name is too long (max 200 characters).");

  const latitude = Number(raw.latitude);
  const longitude = Number(raw.longitude);
  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) throw new ServiceError("Latitude must be between -90 and 90.");
  if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) throw new ServiceError("Longitude must be between -180 and 180.");

  const supplied = Array.isArray(raw.requiredResources) ? raw.requiredResources : [];
  const requiredResources = [];
  for (const item of supplied) {
    const value = String(item).trim();
    if (!RESOURCE_CATEGORIES.includes(value)) throw new ServiceError(`Unknown resource category: ${value}`);
    if (!requiredResources.includes(value)) requiredResources.push(value);
  }

  return { type, severity, affectedPeople: Math.trunc(affected), requiredResources, locationName, latitude, longitude };
}

// ---- mode detection ----

let modePromise = null;

async function probe() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(`${config.apiBase}/api/health`, {
      cache: "no-store",
      signal: controller.signal,
      credentials: "same-origin",
    });
    if (!response.ok) return false;
    const body = await response.json().catch(() => null);
    return Boolean(body && body.status === "ok");
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** "server" when the Python service answers, otherwise "demo". Cached per load. */
export function detectMode() {
  if (!modePromise) {
    modePromise = probe().then((live) => (live ? "server" : (config.allowDemoFallback ? "demo" : "unavailable")));
  }
  return modePromise;
}

/** Test/seam hook. */
export function resetMode() {
  modePromise = null;
}

async function request(method, path, body, options = {}) {
  const init = {
    method,
    cache: "no-store",
    credentials: "same-origin",
    headers: {},
  };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (options.csrf) init.headers["X-CSRF-Token"] = options.csrf;
  if (options.token) init.headers.Authorization = `Bearer ${options.token}`;

  let response;
  try {
    response = await fetch(`${config.apiBase}${path}`, init);
  } catch {
    throw new ServiceError("The admin service could not be reached. Please try again shortly.", 0);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ServiceError(payload.error || "The request could not be completed.", response.status);
  }
  return payload;
}

function bearerToken() {
  try {
    return session().getItem(DEMO_SESSION_KEY + "_token") || null;
  } catch {
    return null;
  }
}

// ---- public form ----

export async function submitRequest(payload) {
  const mode = await detectMode();
  if (mode === "unavailable") {
    throw new ServiceError("The request service is not reachable, and demo fallback is disabled.", 503);
  }
  if (mode === "server") {
    const result = await request("POST", "/api/requests", payload);
    return { request: result.request, mode };
  }
  const record = validateRequestPayload(payload);
  const row = {
    ...record,
    id: newRequestId(),
    status: "pending",
    submittedAt: new Date().toISOString(),
    decidedAt: null,
  };
  writeDemoRequests([row, ...readDemoRequests()]);
  return { request: row, mode };
}

// ---- admin ----

export async function login(passphrase) {
  const mode = await detectMode();

  if (mode === "demo") {
    // Cosmetic gate: nothing here is secret, there is simply no server to keep
    // one. Real authentication stays with the service.
    if (String(passphrase) !== config.demoPassphrase) {
      throw new ServiceError("Incorrect password.", 401);
    }
    try {
      session().setItem(DEMO_SESSION_KEY, "1");
    } catch {
      /* tab-scoped flag is best-effort */
    }
    return { ok: true, csrfToken: null, mode, demo: true };
  }

  const result = await request("POST", "/api/admin/login", { password: passphrase });
  try {
    if (result.sessionToken) session().setItem(DEMO_SESSION_KEY + "_token", result.sessionToken);
  } catch {
    /* private mode: the cookie still carries the session */
  }
  return { ok: true, csrfToken: result.csrfToken || null, mode, demo: false };
}

export async function sessionState() {
  const mode = await detectMode();
  if (mode === "demo") {
    let signedIn = false;
    try {
      signedIn = session().getItem(DEMO_SESSION_KEY) === "1";
    } catch {
      signedIn = false;
    }
    if (!signedIn) throw new ServiceError("Not signed in.", 401);
    return { authenticated: true, csrfToken: null, mode, demo: true };
  }
  const token = bearerToken();
  const result = await request("GET", "/api/admin/session", undefined, { token });
  return { authenticated: true, csrfToken: result.csrfToken || null, mode, demo: false, sessionToken: result.sessionToken };
}

export async function listRequests() {
  const mode = await detectMode();
  if (mode === "demo") {
    try {
      if (session().getItem(DEMO_SESSION_KEY) !== "1") throw new ServiceError("Your admin session has expired. Sign in again.", 401);
    } catch (err) {
      if (err instanceof ServiceError) throw err;
      throw new ServiceError("Your admin session has expired. Sign in again.", 401);
    }
    return { requests: readDemoRequests(), mode, demo: true };
  }
  const result = await request("GET", "/api/admin/requests", undefined, { token: bearerToken() });
  return { requests: Array.isArray(result.requests) ? result.requests : [], mode, demo: false };
}

export async function decideRequest(id, status, csrf) {
  const mode = await detectMode();
  if (mode === "demo") {
    const rows = readDemoRequests();
    const index = rows.findIndex((row) => row.id === id);
    if (index === -1) throw new ServiceError("That request no longer exists.", 404);
    if (rows[index].status !== "pending") {
      throw new ServiceError(`Request ${id} was already ${rows[index].status}.`, 409);
    }
    rows[index] = { ...rows[index], status, decidedAt: new Date().toISOString() };
    writeDemoRequests(rows);
    return { request: rows[index], mode, demo: true };
  }
  const result = await request("PATCH", `/api/admin/requests/${encodeURIComponent(id)}`, { status }, { csrf, token: bearerToken() });
  return { request: result.request, mode, demo: false };
}

export async function logout(csrf) {
  const mode = await detectMode();
  // Read the credential before clearing local state, and pass it explicitly:
  // wiping sessionStorage first would make the call below arrive anonymous and
  // turn every sign-out into a spurious 401.
  const token = bearerToken();
  if (mode !== "demo") {
    try {
      await request("POST", "/api/admin/logout", {}, { csrf, token });
    } catch (err) {
      // A session the server already dropped is still "signed out" as far as the
      // page is concerned; anything else should surface.
      if (err.status !== 401 && err.status !== 403) throw err;
    }
  }
  try {
    session().removeItem(DEMO_SESSION_KEY);
    session().removeItem(DEMO_SESSION_KEY + "_token");
  } catch {
    /* nothing persisted */
  }
  return { ok: true, mode, demo: mode === "demo" };
}

/** Text for the banner both pages show, or null when running for real. */
export async function bannerText() {
  const mode = await detectMode();
  if (mode === "demo") {
    return "DEMO MODE — no server is running, so this sign-in is a formality and requests are stored only in this browser. Deploy backend/admin_server.py for shared, real submissions.";
  }
  if (mode === "unavailable") {
    return "The request service is unreachable and demo fallback is disabled, so submissions will fail until it is started.";
  }
  return null;
}
