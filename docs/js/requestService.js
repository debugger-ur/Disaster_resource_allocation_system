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
const DEMO_INVENTORY_KEY = "drras_inventory";
const PROBE_TIMEOUT_MS = 2000;

const DISASTER_TYPES = ["FLOOD", "EARTHQUAKE", "FIRE", "LANDSLIDE", "INDUSTRIAL_ACCIDENT", "OTHER"];
const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const RESOURCE_CATEGORIES = ["Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply"];
const MAX_RESOURCE_QUANTITY = 1_000_000_000;
const MESSAGE_MAX_LENGTH = 1000;

// Mirrors DEFAULT_INVENTORY / the default decision messages in backend/admin_server.py.
const DEFAULT_INVENTORY = {
  Ambulance: 3,
  RescueTeam: 18,
  MedicalTeam: 5,
  Equipment: 2,
  Supply: 1500,
};
const DEFAULT_DECISION_MESSAGES = {
  accepted:
    "Your relief request has been ACCEPTED by the command center. Relief units are being dispatched to your location. Please stay in a safe, accessible area and keep your communication line open.",
  rejected:
    "Your relief request has been reviewed and REJECTED by the command center. This typically happens when the zone is already covered by ongoing operations or the request was merged with a duplicate. If you are in immediate danger, please contact local emergency services (112).",
};
export { DEFAULT_DECISION_MESSAGES };

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

// Demo-mode stock of supplies. Seeded from the same defaults the server uses.
function readDemoInventory() {
  try {
    const raw = storage().getItem(DEMO_INVENTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === "object") return { ...DEFAULT_INVENTORY, ...parsed };
  } catch {
    /* fall through to defaults */
  }
  return { ...DEFAULT_INVENTORY };
}

function writeDemoInventory(inventory) {
  try {
    storage().setItem(DEMO_INVENTORY_KEY, JSON.stringify(inventory));
  } catch (err) {
    throw new ServiceError(`This browser could not save the inventory (${err?.name || "error"}).`, 500);
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

  // Quantities are optional (the form used to send categories only). A category
  // with a quantity always lands in requiredResources as well.
  const quantitiesRaw = raw.resourceQuantities ?? {};
  if (typeof quantitiesRaw !== "object" || Array.isArray(quantitiesRaw)) {
    throw new ServiceError("Resource quantities must be an object of category: amount pairs.");
  }
  const resourceQuantities = {};
  for (const [category, amount] of Object.entries(quantitiesRaw)) {
    const name = String(category).trim();
    if (!RESOURCE_CATEGORIES.includes(name)) throw new ServiceError(`Unknown resource category: ${name}`);
    const value = Number(amount);
    if (!Number.isFinite(value) || value < 0 || value > MAX_RESOURCE_QUANTITY) {
      throw new ServiceError(`Quantity for ${name} must be a number between 0 and ${MAX_RESOURCE_QUANTITY}.`);
    }
    const quantity = Math.trunc(value);
    if (quantity === 0) continue;
    resourceQuantities[name] = quantity;
    if (!requiredResources.includes(name)) requiredResources.push(name);
  }

  return {
    type,
    severity,
    affectedPeople: Math.trunc(affected),
    requiredResources,
    resourceQuantities,
    locationName,
    latitude,
    longitude,
  };
}

/** Mirrors plan_submission_grant() in backend/admin_server.py: what the user is
 *  promised the moment they ask, given the supplies on hand right now. */
export function planSubmissionGrant(requested, available, severity) {
  const entries = Object.entries(requested || {});
  if (entries.length === 0) return { granted: {}, message: null };
  const short = entries.filter(([category, quantity]) => quantity > (available[category] || 0));
  if (short.length === 0) return { granted: { ...requested }, message: null };
  if (severity === "CRITICAL") {
    const granted = {};
    for (const [category, quantity] of entries) {
      const amount = Math.min(quantity, available[category] || 0);
      if (amount > 0) granted[category] = amount;
    }
    const detail = short
      .map(([category, quantity]) => `${granted[category] || 0} of ${quantity} ${category} (in stock now: ${available[category] || 0})`)
      .join("; ");
    return {
      granted,
      message:
        `Critical situation: the supplies you asked for are beyond the limits of what is in stock right now. ` +
        `You are guaranteed at least the supplies present at this moment: ${detail}. ` +
        `In other words, this much only can be provided at the moment; the rest will be dispatched when supplies are replenished.`,
    };
  }
  const detail = short
    .map(([category, quantity]) => `${category}: asked ${quantity}, in stock ${available[category] || 0}`)
    .join("; ");
  return {
    granted: {},
    message:
      `The supplies you asked for are beyond the limits of what is in stock right now (${detail}). ` +
      `Your request has been flagged for admin review; an admin will decide what can be provided at the moment.`,
  };
}

function escapeText(value) {
  return String(value).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}

/** Mirrors validate_decision_message() in backend/admin_server.py: trims and
 *  length-checks the admin note. The server escapes HTML on store; the demo
 *  path calls escapeText() itself so both modes persist the same shape. */
export function sanitizeDecisionMessage(raw) {
  if (raw === undefined || raw === null) return null;
  const text = String(raw).trim();
  if (!text) return null;
  if (text.length > MESSAGE_MAX_LENGTH) {
    throw new ServiceError(`Message is too long (max ${MESSAGE_MAX_LENGTH} characters).`);
  }
  return text;
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
  const { granted, message } = planSubmissionGrant(
    record.resourceQuantities,
    readDemoInventory(),
    record.severity,
  );
  const row = {
    ...record,
    grantedResources: granted,
    userMessage: message,
    decisionMessage: null,
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

export async function decideRequest(id, status, csrf, message = null) {
  const mode = await detectMode();
  const cleanMessage = sanitizeDecisionMessage(message);
  if (mode === "demo") {
    const rows = readDemoRequests();
    const index = rows.findIndex((row) => row.id === id);
    if (index === -1) throw new ServiceError("That request no longer exists.", 404);
    if (rows[index].status !== "pending") {
      throw new ServiceError(`Request ${id} was already ${rows[index].status}.`, 409);
    }
    const row = rows[index];
    let decisionMessage = (cleanMessage ? escapeText(cleanMessage) : null)
      || DEFAULT_DECISION_MESSAGES[status]
      || DEFAULT_DECISION_MESSAGES.rejected;
    let granted = {};
    if (status === "accepted") {
      const inventory = readDemoInventory();
      const requested = row.resourceQuantities || {};
      for (const [category, quantity] of Object.entries(requested)) {
        const delivered = Math.min(quantity, inventory[category] || 0);
        if (delivered > 0) {
          granted[category] = delivered;
          inventory[category] = (inventory[category] || 0) - delivered;
        }
      }
      writeDemoInventory(inventory);
      const short = Object.entries(requested).filter(([category, quantity]) => (granted[category] || 0) < quantity);
      if (short.length > 0) {
        const detail = short.map(([category, quantity]) => `${granted[category] || 0} of ${quantity} ${category}`).join("; ");
        decisionMessage += ` Supplies note: only the stock at this moment could be provided — ${detail}; this much only can be provided at the moment. The remainder follows when supplies are replenished.`;
      }
    }
    rows[index] = {
      ...row,
      status,
      grantedResources: granted,
      decisionMessage,
      decidedAt: new Date().toISOString(),
    };
    writeDemoRequests(rows);
    return { request: rows[index], mode, demo: true };
  }
  const body = cleanMessage ? { status, message: cleanMessage } : { status };
  const result = await request("PATCH", `/api/admin/requests/${encodeURIComponent(id)}`, body, { csrf, token: bearerToken() });
  return { request: result.request, mode, demo: false };
}

/** Public status check: the user looks up their own request by ID and reads the
 *  allocation note and the admin's decision message. */
export async function getRequestStatus(id) {
  const mode = await detectMode();
  if (mode === "unavailable") {
    throw new ServiceError("The request service is not reachable, and demo fallback is disabled.", 503);
  }
  const requestId = String(id || "").trim();
  if (!requestId) throw new ServiceError("Enter your Request ID (e.g. REQ-1A2B3C4D).");
  if (mode === "demo") {
    const row = readDemoRequests().find((item) => item.id.toUpperCase() === requestId.toUpperCase());
    if (!row) throw new ServiceError("That request was not found in this browser.", 404);
    return { request: row, mode, demo: true };
  }
  const result = await request("GET", `/api/requests/${encodeURIComponent(requestId)}`);
  return { request: result.request, mode, demo: false };
}

/** Supplies currently on hand per category ("at this moment"). */
export async function fetchInventory() {
  const mode = await detectMode();
  if (mode === "demo") return { inventory: readDemoInventory(), mode, demo: true };
  if (mode === "unavailable") return { inventory: { ...DEFAULT_INVENTORY }, mode, demo: false };
  try {
    const result = await request("GET", "/api/inventory");
    return { inventory: result.inventory || {}, mode, demo: false };
  } catch {
    return { inventory: { ...DEFAULT_INVENTORY }, mode, demo: false };
  }
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
