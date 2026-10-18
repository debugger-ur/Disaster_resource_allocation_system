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
const DEMO_NOTIFICATIONS_KEY = "drras_notifications";
const DEMO_INVENTORY_KEY = "drras_inventory";
const DEMO_SESSION_KEY = "drras_demo_admin";
const NOTIFICATION_TOKEN_KEY = "drras_notification_token";
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

function readStoredArray(key) {
  try {
    const raw = storage().getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeStoredArray(key, rows) {
  try {
    storage().setItem(key, JSON.stringify(rows));
  } catch (err) {
    throw new ServiceError(`This browser could not save data (${err?.name || "error"}).`, 500);
  }
}

function getNotificationToken() {
  try {
    return storage().getItem(NOTIFICATION_TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

function saveNotificationToken(token) {
  if (!token) return;
  try {
    storage().setItem(NOTIFICATION_TOKEN_KEY, token);
  } catch {
    // The request is still saved; the user can see its notification token in the
    // response only on a non-browser API client if storage is unavailable.
  }
}

function ensureDemoNotificationToken() {
  let token = getNotificationToken();
  if (!token) {
    token = `demo-${newRequestId()}-${newRequestId()}`;
    saveNotificationToken(token);
  }
  return token;
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

  const itemName = String(raw.itemName ?? requiredResources[0] ?? "Relief supplies").trim();
  if (!itemName) throw new ServiceError("Resource item name is required.");
  if (itemName.length > 100) throw new ServiceError("Resource item name is too long (max 100 characters).");
  const requestedQuantity = raw.requestedQuantity == null ? 0 : Number(raw.requestedQuantity);
  if (!Number.isInteger(requestedQuantity) || requestedQuantity < 0 || requestedQuantity > 1_000_000_000) {
    throw new ServiceError("Requested quantity must be a whole number between 0 and 1,000,000,000.");
  }
  const isCritical = raw.isCritical == null ? severity === "CRITICAL" : raw.isCritical;
  if (typeof isCritical !== "boolean") throw new ServiceError("isCritical must be a boolean.");

  return {
    type, severity, affectedPeople: Math.trunc(affected), requiredResources,
    locationName, latitude, longitude, itemName, requestedQuantity, isCritical,
  };
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
  if (options.notificationToken) init.headers["X-Notification-Token"] = options.notificationToken;

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
    const result = await request("POST", "/api/requests", payload, {
      notificationToken: getNotificationToken(),
    });
    saveNotificationToken(result.notificationToken);
    return { request: result.request, mode };
  }
  const record = validateRequestPayload(payload);
  ensureDemoNotificationToken();
  const row = {
    ...record,
    id: newRequestId(),
    status: "pending",
    allocatedQuantity: 0,
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

function requireDemoAdmin() {
  try {
    if (session().getItem(DEMO_SESSION_KEY) !== "1") {
      throw new ServiceError("Your admin session has expired. Sign in again.", 401);
    }
  } catch (err) {
    if (err instanceof ServiceError) throw err;
    throw new ServiceError("Your admin session has expired. Sign in again.", 401);
  }
}

export async function listRequests() {
  const mode = await detectMode();
  if (mode === "demo") {
    requireDemoAdmin();
    return { requests: readDemoRequests(), mode, demo: true };
  }
  const result = await request("GET", "/api/admin/requests", undefined, { token: bearerToken() });
  return { requests: Array.isArray(result.requests) ? result.requests : [], mode, demo: false };
}

export async function listInventory() {
  const mode = await detectMode();
  if (mode === "demo") {
    requireDemoAdmin();
    return { inventory: readStoredArray(DEMO_INVENTORY_KEY), mode, demo: true };
  }
  const result = await request("GET", "/api/admin/inventory", undefined, { token: bearerToken() });
  return { inventory: Array.isArray(result.inventory) ? result.inventory : [], mode, demo: false };
}

export async function setInventoryQuantity(itemName, availableQuantity, csrf) {
  const cleanedName = String(itemName ?? "").trim();
  const quantity = Number(availableQuantity);
  if (!cleanedName || cleanedName.length > 100) throw new ServiceError("Enter a resource item name (max 100 characters).");
  if (!Number.isInteger(quantity) || quantity < 0 || quantity > 1_000_000_000) {
    throw new ServiceError("Available quantity must be a whole number from 0 to 1,000,000,000.");
  }

  const mode = await detectMode();
  if (mode === "demo") {
    requireDemoAdmin();
    const inventory = readStoredArray(DEMO_INVENTORY_KEY);
    const index = inventory.findIndex((item) => item.itemName.toLowerCase() === cleanedName.toLowerCase());
    const item = { itemName: cleanedName, availableQuantity: quantity, updatedAt: new Date().toISOString() };
    if (index < 0) inventory.push(item);
    else inventory[index] = item;
    writeStoredArray(DEMO_INVENTORY_KEY, inventory);
    return { item, mode, demo: true };
  }
  const result = await request("POST", "/api/admin/inventory", {
    itemName: cleanedName,
    availableQuantity: quantity,
  }, { csrf, token: bearerToken() });
  return { item: result.item, mode, demo: false };
}

function decisionMessage(request, status, reason) {
  const requested = Number(request.requestedQuantity || 0);
  const allocated = Number(request.allocatedQuantity || 0);
  const item = request.itemName || request.requiredResources?.[0] || "Relief supplies";
  if (status === "accepted") {
    return `Your request #${request.id} for ${requested} ${item} has been approved. You will receive the full requested quantity.`;
  }
  if (status === "partially_approved") {
    return `Your request #${request.id} for ${requested} ${item} has been partially approved. It is critical, but only ${allocated} units are currently in stock. We are providing ${allocated} units now. The remaining amount will be provided later if more supplies arrive.`;
  }
  const why = String(reason || "Insufficient stock / not prioritized at this time").trim();
  const ending = /[.!?]$/.test(why) ? "" : ".";
  return `Your request #${request.id} for ${requested} ${item} has been rejected. Reason: ${why}${ending}`;
}

function decideDemoRequest(request, requestedStatus, reason) {
  const quantity = Number(request.requestedQuantity || 0);
  const inventory = readStoredArray(DEMO_INVENTORY_KEY);
  const stockIndex = inventory.findIndex(
    (item) => item.itemName.toLowerCase() === String(request.itemName || "").toLowerCase(),
  );
  const available = stockIndex < 0 ? 0 : Number(inventory[stockIndex].availableQuantity || 0);
  let status = "rejected";
  let allocatedQuantity = 0;
  let decisionReason = null;

  if (requestedStatus === "rejected") {
    decisionReason = reason || "Not prioritized at this time.";
  } else if (quantity === 0 || quantity <= available) {
    status = "accepted";
    allocatedQuantity = quantity;
    if (quantity > 0 && stockIndex >= 0) {
      inventory[stockIndex] = { ...inventory[stockIndex], availableQuantity: available - quantity, updatedAt: new Date().toISOString() };
      writeStoredArray(DEMO_INVENTORY_KEY, inventory);
    }
  } else if (request.isCritical && available > 0) {
    status = "partially_approved";
    allocatedQuantity = available;
    inventory[stockIndex] = { ...inventory[stockIndex], availableQuantity: 0, updatedAt: new Date().toISOString() };
    writeStoredArray(DEMO_INVENTORY_KEY, inventory);
  } else {
    decisionReason = request.isCritical
      ? "Insufficient stock; none is currently available."
      : "Insufficient stock; this request was not marked critical and was not prioritized at this time.";
  }

  const updated = {
    ...request,
    status,
    allocatedQuantity,
    decisionReason,
    decidedAt: new Date().toISOString(),
  };
  return { request: updated, messageToUser: decisionMessage(updated, status, decisionReason) };
}

export async function decideRequest(id, status, csrf, reason = null) {
  const mode = await detectMode();
  if (mode === "demo") {
    requireDemoAdmin();
    const rows = readDemoRequests();
    const index = rows.findIndex((row) => row.id === id);
    if (index === -1) throw new ServiceError("That request no longer exists.", 404);
    if (rows[index].status !== "pending") {
      throw new ServiceError(`Request ${id} was already ${rows[index].status}.`, 409);
    }
    const decision = decideDemoRequest(rows[index], status, reason);
    rows[index] = decision.request;
    writeDemoRequests(rows);
    const notification = {
      id: newRequestId(),
      requestId: id,
      message: decision.messageToUser,
      status: "UNREAD",
      createdAt: new Date().toISOString(),
    };
    writeStoredArray(DEMO_NOTIFICATIONS_KEY, [notification, ...readStoredArray(DEMO_NOTIFICATIONS_KEY)]);
    return { ...decision, mode, demo: true };
  }
  const result = await request(
    "PATCH",
    `/api/admin/requests/${encodeURIComponent(id)}`,
    { status, reason },
    { csrf, token: bearerToken() },
  );
  return {
    request: result.request,
    messageToUser: result.message_to_user,
    notification: result.notification,
    mode,
    demo: false,
  };
}

export async function listNotifications() {
  const token = getNotificationToken();
  if (!token) throw new ServiceError("No notification profile is linked to this browser yet. Submit a relief request first.", 401);
  const mode = await detectMode();
  if (mode === "demo") {
    return { notifications: readStoredArray(DEMO_NOTIFICATIONS_KEY), mode, demo: true };
  }
  const result = await request("GET", "/api/notifications", undefined, { notificationToken: token });
  return { notifications: Array.isArray(result.notifications) ? result.notifications : [], mode, demo: false };
}

export async function markNotificationRead(id) {
  const token = getNotificationToken();
  if (!token) throw new ServiceError("No notification profile is linked to this browser yet. Submit a relief request first.", 401);
  const mode = await detectMode();
  if (mode === "demo") {
    const notifications = readStoredArray(DEMO_NOTIFICATIONS_KEY);
    const index = notifications.findIndex((notification) => String(notification.id) === String(id));
    if (index < 0) throw new ServiceError("That notification was not found.", 404);
    notifications[index] = { ...notifications[index], status: "READ" };
    writeStoredArray(DEMO_NOTIFICATIONS_KEY, notifications);
    return { notification: notifications[index], mode, demo: true };
  }
  const result = await request(
    "PATCH",
    `/api/notifications/${encodeURIComponent(id)}`,
    { status: "READ" },
    { notificationToken: token },
  );
  return { notification: result.notification, mode, demo: false };
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
