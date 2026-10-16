const loginSection = document.getElementById("loginSection");
const dashboardSection = document.getElementById("dashboardSection");
const loginForm = document.getElementById("loginForm");
const loginButton = document.getElementById("loginButton");
const adminPassword = document.getElementById("adminPassword");
const loginMessage = document.getElementById("loginMessage");
const dashboardMessage = document.getElementById("dashboardMessage");
const requestRows = document.getElementById("requestRows");
const emptyState = document.getElementById("emptyState");
const statusFilter = document.getElementById("statusFilter");

let csrfToken = null;
let requests = [];
// When the app is embedded in a frame on another site, a browser may refuse to
// carry the session cookie at all - sign-in then looks like an instant expiry.
// A bearer token the page sends explicitly is unaffected. Server opt-in:
// --allow-bearer-auth. sessionStorage (not localStorage) so it dies with the tab.
const TOKEN_KEY = "drras_admin_token";
let bearerToken = readStoredToken();

function readStoredToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function rememberToken(token) {
  bearerToken = token || null;
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: keep the token in memory only */
  }
}
// A 401 immediately after signing in is not an expired session - it means the
// browser never sent the cookie back (cross-site frame, or Secure cookie over
// http). Saying "expired" there sends you looking in the wrong place.
let dashboardOpenedAt = 0;

function sessionLostMessage() {
  if (dashboardOpenedAt && Date.now() - dashboardOpenedAt < 20000) {
    return bearerToken
      ? "Signed in, but the server rejected the session token it just issued. The server was probably restarted - sign in again."
      : "Signed in, but the browser is not returning the session cookie. Open this site in its own tab, or start the server with --allow-bearer-auth (works inside frames).";
  }
  return "Your admin session has expired. Sign in again.";
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (bearerToken) headers.Authorization = `Bearer ${bearerToken}`;
  const response = await fetch(url, {
    ...options,
    credentials: "same-origin",
    cache: "no-store",
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) rememberToken(null);
  if (!response.ok) {
    throw new ApiError(body.error || "The request could not be completed.", response.status);
  }
  return body;
}

function showLogin(message = "") {
  csrfToken = null;
  loginSection.hidden = false;
  dashboardSection.hidden = true;
  loginMessage.textContent = message;
  dashboardMessage.textContent = "";
  if (!message) adminPassword.focus();
}

function showDashboard(token) {
  csrfToken = token;
  loginSection.hidden = true;
  dashboardSection.hidden = false;
  loginMessage.textContent = "";
}

function element(tagName, className, value) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = String(value);
  return node;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value || "—"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function setSummaryCounts(allRequests) {
  const counts = { pending: 0, accepted: 0, rejected: 0 };
  allRequests.forEach((request) => {
    if (Object.hasOwn(counts, request.status)) counts[request.status] += 1;
  });
  document.getElementById("pendingCount").textContent = counts.pending;
  document.getElementById("acceptedCount").textContent = counts.accepted;
  document.getElementById("rejectedCount").textContent = counts.rejected;
  document.getElementById("totalCount").textContent = allRequests.length;
}

function renderRequests() {
  requestRows.replaceChildren();
  const filter = statusFilter.value;
  const visible = filter === "all" ? requests : requests.filter((item) => item.status === filter);
  document.getElementById("requestCount").textContent =
    `${visible.length} ${visible.length === 1 ? "request" : "requests"}`;
  emptyState.hidden = visible.length !== 0;

  for (const request of visible) {
    const row = document.createElement("tr");

    const requestCell = element("td");
    const titleLine = element("div", "request-type");
    titleLine.append(element("span", "", request.type.replaceAll("_", " ")));
    const severity = element(
      "span",
      `severity severity-${String(request.severity).toLowerCase()}`,
      request.severity,
    );
    titleLine.append(severity);
    requestCell.append(titleLine, element("span", "request-id", request.id));
    requestCell.append(
      element(
        "div",
        "request-meta",
        `${Number(request.affectedPeople).toLocaleString()} people affected`,
      ),
    );

    const locationCell = element("td");
    locationCell.append(element("div", "", request.locationName));
    locationCell.append(
      element(
        "div",
        "location-coords",
        `${Number(request.latitude).toFixed(4)}, ${Number(request.longitude).toFixed(4)}`,
      ),
    );

    const resourcesCell = element("td");
    resourcesCell.append(
      element(
        "div",
        "resource-list",
        request.requiredResources?.length ? request.requiredResources.join(", ") : "No specific resources",
      ),
    );

    const submittedCell = element("td");
    submittedCell.append(element("div", "submitted-time", formatDate(request.submittedAt)));

    const decisionCell = element("td", "decision-cell");
    decisionCell.append(
      element("span", `status-pill status-${request.status}`, request.status),
    );
    if (request.decidedAt) {
      decisionCell.append(element("div", "reviewed-note", `Reviewed ${formatDate(request.decidedAt)}`));
    }

    const actionsCell = element("td", "action-cell");
    if (request.status === "pending") {
      const acceptButton = element("button", "button action-button action-accept", "Accept");
      acceptButton.type = "button";
      acceptButton.dataset.requestId = request.id;
      acceptButton.dataset.action = "accepted";
      acceptButton.setAttribute("aria-label", `Accept request ${request.id}`);

      const rejectButton = element("button", "button action-button action-reject", "Reject");
      rejectButton.type = "button";
      rejectButton.dataset.requestId = request.id;
      rejectButton.dataset.action = "rejected";
      rejectButton.setAttribute("aria-label", `Reject request ${request.id}`);
      actionsCell.append(acceptButton, rejectButton);
    } else {
      actionsCell.append(element("span", "reviewed-note", "Reviewed"));
    }

    row.append(requestCell, locationCell, resourcesCell, submittedCell, decisionCell, actionsCell);
    requestRows.append(row);
  }
}

async function loadRequests() {
  dashboardMessage.textContent = "";
  const result = await api("/api/admin/requests");
  requests = Array.isArray(result.requests) ? result.requests : [];
  setSummaryCounts(requests);
  renderRequests();
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginMessage.textContent = "";
  loginButton.disabled = true;
  loginButton.textContent = "Signing in…";
  try {
    const result = await api("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: adminPassword.value }),
    });
    adminPassword.value = "";
    rememberToken(result.sessionToken || null);
    dashboardOpenedAt = Date.now();
    showDashboard(result.csrfToken);
    try {
      await loadRequests();
    } catch (error) {
      if (error.status === 401) showLogin(sessionLostMessage());
      else dashboardMessage.textContent = error.message;
    }
  } catch (error) {
    loginMessage.textContent = error instanceof TypeError
      ? "The admin service could not be reached. Please try again shortly."
      : error.message;
  } finally {
    loginButton.disabled = false;
    loginButton.textContent = "Sign in";
  }
});

statusFilter.addEventListener("change", renderRequests);

document.getElementById("refreshButton").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  dashboardMessage.textContent = "";
  try {
    await loadRequests();
  } catch (error) {
    if (error.status === 401) showLogin(sessionLostMessage());
    else dashboardMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

requestRows.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action][data-request-id]");
  if (!button || button.disabled) return;
  const request = requests.find((item) => item.id === button.dataset.requestId);
  if (!request || request.status !== "pending") return;

  const action = button.dataset.action;
  if (action === "rejected" && !window.confirm(`Reject request ${request.id}?`)) return;

  const rowButtons = button.closest("tr").querySelectorAll("button");
  rowButtons.forEach((item) => { item.disabled = true; });
  dashboardMessage.textContent = "";
  try {
    await api(`/api/admin/requests/${encodeURIComponent(request.id)}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({ status: action }),
    });
    await loadRequests();
  } catch (error) {
    if (error.status === 401) showLogin(sessionLostMessage());
    else {
      await loadRequests().catch(() => {});
      dashboardMessage.textContent = error.message;
    }
  }
});

document.getElementById("logoutButton").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await api("/api/admin/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    });
    rememberToken(null);
    showLogin("You have been signed out.");
  } catch (error) {
    if (error.status === 401) showLogin(sessionLostMessage());
    else dashboardMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function initialize() {
  try {
    const session = await api("/api/admin/session");
    if (session.sessionToken) rememberToken(session.sessionToken);
    showDashboard(session.csrfToken);
    await loadRequests();
  } catch (error) {
    if (error.status === 401) showLogin();
    else showLogin("The admin service could not be reached. Please try again shortly.");
  }
}

initialize();
