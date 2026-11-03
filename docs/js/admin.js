import { api, setCsrf, setBearer, setUnauthorizedHandler } from "./api.js";
import { DrrasMap, CATEGORY_META } from "./map.js";
import {
  qs,
  qsa,
  esc,
  icon,
  debounce,
  fmtDateTime,
  fmtRelative,
  fmtNumber,
  fmtDistance,
  fmtDuration,
  fmtBytes,
  titleCase,
  statusBadge,
  riskBadge,
  severityBadge,
  availabilityBadge,
  resourceLabel,
  itemsSummary,
  stockSummary,
  copyText,
  STATUS_META,
  RESOURCE_ORDER,
} from "./format.js";

const TOKEN_KEY = "drras_admin_token";
const DISASTER_TYPES = [
  ["FLOOD", "Flood"],
  ["EARTHQUAKE", "Earthquake"],
  ["FIRE", "Fire"],
  ["LANDSLIDE", "Landslide"],
  ["INDUSTRIAL_ACCIDENT", "Industrial accident"],
  ["OTHER", "Other"],
];
const OPEN_STATUSES = new Set([
  "submitted",
  "under_verification",
  "possible_duplicate",
  "awaiting_approval",
]);
const ALLOCATABLE = new Set(["approved", "resources_assigned", "in_progress"]);
const SEVERITY_RANK = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };

const state = {
  role: null,
  requests: [],
  centres: [],
  stats: null,
  settings: null,
  defaults: null,
  routing: null,
  inventory: {},
  audit: [],
  currentView: "overview",
  queueFilter: "all",
  selectedRequest: null,
  recommendations: null,
  adminMapLayers: new Set(Object.keys(CATEGORY_META).filter((key) => key !== "user")),
  centresFilter: { search: "", category: "" },
  auditLimit: 200,
  centreEditingId: null,
  displayedAt: null,
};

const maps = { overview: null, operations: null };
let dialogHandler = null;
let lastFocus = null;
let refreshTimer = null;

/* ------------------------------------------------------------------ */
/* Boot                                                               */
/* ------------------------------------------------------------------ */

document.addEventListener("DOMContentLoaded", () => {
  wireLogin();
  wireShell();
  wireRequests();
  wireDrawer();
  wireDialogs();
  wireSettings();
  wireCentres();
  wireAudit();
  wireMaps();
  void restoreSession();
  void checkService();
});

setUnauthorizedHandler((message) => {
  if (qs("#appView")?.hidden) return;
  showLogin(message || "Your session expired. Sign in again.");
});

async function checkService() {
  const node = qs("#serviceStatus");
  try {
    const health = await api.health();
    if (node) {
      node.textContent = health.passwordConfigured
        ? `Service online · ${health.demoData ? "demo data present" : "live database"}`
        : "Service online, but no password is configured. Run --set-password on the server.";
    }
  } catch {
    if (node) {
      node.innerHTML =
        "Service unreachable. Start it with <span class='inline-code'>python3 backend/admin_server.py</span>.";
    }
  }
}

async function restoreSession() {
  const saved = sessionStorage.getItem(TOKEN_KEY);
  if (saved) setBearer(saved);
  try {
    const session = await api.session();
    await enterApp(session);
  } catch {
    setBearer(null);
    sessionStorage.removeItem(TOKEN_KEY);
    showLogin("");
  }
}

function wireLogin() {
  qs("#loginForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = qs("#loginButton");
    const message = qs("#loginMessage");
    const password = qs("#adminPassword").value;
    message.textContent = "";
    if (!password) {
      message.textContent = "Enter your password.";
      return;
    }
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span> Signing in…`;
    try {
      const result = await api.login(password);
      setCsrf(result.csrfToken);
      if (result.sessionToken) {
        setBearer(result.sessionToken);
        sessionStorage.setItem(TOKEN_KEY, result.sessionToken);
      }
      qs("#adminPassword").value = "";
      await enterApp({
        authenticated: true,
        csrfToken: result.csrfToken,
        role: result.role,
        sessionToken: result.sessionToken,
      });
    } catch (error) {
      message.textContent =
        error.status === 429
          ? error.message
          : error.status === 401
            ? "Incorrect password."
            : error.message;
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
  });
}

async function enterApp(session) {
  if (session?.csrfToken) setCsrf(session.csrfToken);
  if (session?.sessionToken) {
    setBearer(session.sessionToken);
    sessionStorage.setItem(TOKEN_KEY, session.sessionToken);
  }
  state.role = session?.role || "admin";
  qs("#loginView").hidden = true;
  qs("#appView").hidden = false;
  applyRoleUI();
  qs("#pageTitle").textContent = "Overview";
  await loadAll({ first: true });
  showView("overview", { silent: true });
}

function applyRoleUI() {
  const admin = state.role === "admin";
  qs("#userRole").textContent = admin ? "Administrator" : "Operator";
  qs("#userAvatar").textContent = admin ? "AD" : "OP";
  qs("#userScope").textContent = admin ? "Full access" : "Review & allocation";
  qs("#roleBadge").textContent = admin ? "Admin" : "Operator";
  qs("#roleBadge").className = admin ? "badge badge--ok" : "badge badge--info";
  qs("#settingsRoleNote").textContent = admin ? "Administrator only" : "Read-only for your role";
  qs("#roleExplanation").textContent = admin
    ? "Administrators can change settings, stock and centres. Operators can review, approve and allocate, but cannot change configuration."
    : "You are signed in as an operator: review, approve, reject, merge and allocate are available, but configuration and centre editing are restricted to administrators.";
  if (!admin) {
    qsa("#viewSettings input, #viewSettings select").forEach((node) => {
      node.disabled = true;
    });
    qsa("#viewSettings button").forEach((node) => {
      node.disabled = true;
    });
  }
  qs("#addCentreButton").hidden = !admin;
}

function showLogin(message = "") {
  qs("#appView").hidden = true;
  qs("#loginView").hidden = false;
  qs("#loginMessage").textContent = message;
  closeDrawer();
  setCsrf(null);
  setBearer(null);
  sessionStorage.removeItem(TOKEN_KEY);
  setTimeout(() => qs("#adminPassword")?.focus(), 60);
}

/* ------------------------------------------------------------------ */
/* Shell / navigation                                                 */
/* ------------------------------------------------------------------ */

function wireShell() {
  qsa(".sidebar__link[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.view) showView(button.dataset.view);
    });
  });
  document.addEventListener("click", (event) => {
    const go = event.target.closest("[data-go]");
    if (go) {
      event.preventDefault();
      showView(go.dataset.go);
    }
    const queueJump = event.target.closest("[data-queue-jump]");
    if (queueJump) {
      state.queueFilter = queueJump.dataset.queueJump;
      showView("queue");
    }
  });
  qs("#openQueueButton")?.addEventListener("click", () => {
    state.queueFilter = "all";
    showView("queue");
  });
  qs("#refreshButton")?.addEventListener("click", () => refreshAll({ manual: true }));
  qs("#logoutButton")?.addEventListener("click", async () => {
    try {
      await api.logout();
    } catch {
      /* a dead session is still signed out */
    }
    sessionStorage.removeItem(TOKEN_KEY);
    showLogin("You have signed out.");
  });
  qs("#menuButton")?.addEventListener("click", () => toggleSidebar(true));
  qs("#sidebarBackdrop")?.addEventListener("click", () => toggleSidebar(false));
  window.addEventListener("hashchange", () => {
    const target = location.hash.replace("#", "");
    if (target) showView(target, { silent: true });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !qs("#requestDrawer").hidden) closeDrawer();
  });
}

function toggleSidebar(open) {
  const sidebar = qs("#sidebar");
  const backdrop = qs("#sidebarBackdrop");
  sidebar.classList.toggle("is-open", open);
  backdrop.classList.toggle("is-open", open);
  qs("#menuButton")?.setAttribute("aria-expanded", String(open));
}

function showView(view, { silent = false } = {}) {
  const known = ["overview", "queue", "requests", "map", "centres", "audit", "settings"];
  if (!known.includes(view)) view = "overview";
  state.currentView = view;
  qsa(".admin-view").forEach((section) => {
    section.hidden = section.dataset.view !== view;
  });
  qsa(".sidebar__link[data-view]").forEach((button) => {
    if (button.dataset.view === view) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  const meta = {
    overview: ["Overview", "Live operational snapshot"],
    queue: ["Verification queue", "Reports waiting for a human decision"],
    requests: ["All requests", "Search, filter and open any report"],
    map: ["Operations map", "Incidents and the help-centre network"],
    centres: ["Help centres & stock", "Inventory used for allocation"],
    audit: ["Audit log", "Who did what, when and why"],
    settings: ["Settings", "Approval automation, thresholds and routing"],
  }[view];
  qs("#pageTitle").textContent = meta[0];
  qs("#pageSub").textContent = meta[1];
  if (location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
  toggleSidebar(false);
  if (view === "overview") renderOverview();
  if (view === "queue") renderQueue();
  if (view === "requests") renderRequestsView();
  if (view === "map") renderOperationsMap();
  if (view === "centres") renderCentres();
  if (view === "audit") renderAudit();
  if (view === "settings") renderSettings();
  requestAnimationFrame(() => {
    maps.overview?.invalidate();
    maps.operations?.invalidate();
  });
  if (!silent) window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ------------------------------------------------------------------ */
/* Data                                                               */
/* ------------------------------------------------------------------ */

async function loadAll({ first = false, quiet = false } = {}) {
  try {
    const [requests, stats, centres, settings, audit, inventory] = await Promise.all([
      api.adminRequests(),
      api.adminStats(),
      api.adminCentres(),
      api.adminSettings(),
      api.adminAudit({ limit: 300 }),
      api.adminInventory(),
    ]);
    state.requests = requests.requests || [];
    state.stats = stats;
    state.centres = centres.centres || [];
    state.settings = settings.settings || {};
    state.defaults = settings.defaults || {};
    state.routing = settings.routing || null;
    state.audit = audit.audit || [];
    state.inventory = inventory.inventory || {};
    state.displayedAt = new Date();
    renderAll();
  } catch (error) {
    if (error.status === 401) {
      showLogin("Your session has expired. Sign in again.");
      return;
    }
    if (!quiet) toast("Could not load data", error.message, "error");
    if (first) {
      qs("#appBanner").innerHTML = `<div class="notice notice--danger" style="margin-bottom:4px">
        ${icon("alert", 18)}<span><strong>Data could not be loaded.</strong> ${esc(error.message)}</span></div>`;
    }
  }
}

async function refreshAll({ manual = false, quiet = false } = {}) {
  const button = qs("#refreshButton");
  if (button && manual) {
    button.disabled = true;
    button.innerHTML = `<span class="spinner spinner--dark"></span> Refreshing`;
  }
  await loadAll({ quiet });
  if (state.selectedRequest) {
    await openRequest(state.selectedRequest.id, { keepScroll: true });
  }
  if (button && manual) {
    button.disabled = false;
    button.innerHTML = `${icon("refresh", 15)} Refresh`;
  }
}

function renderAll() {
  renderNavCounts();
  renderOverview();
  renderQueue();
  renderRequestsView();
  renderCentres();
  renderAudit();
  renderSettings();
  renderOperationsMap();
  if (state.selectedRequest) renderDrawer(state.selectedRequest);
  setText("#lastUpdated", `Updated ${fmtRelative(state.displayedAt.toISOString())}`);
}

function renderNavCounts() {
  const queues = state.stats?.queues || {};
  const open = (state.stats?.requests?.awaitingVerification || 0) + (state.stats?.requests?.possibleDuplicates || 0);
  const count = qs("#navQueueCount");
  if (count) {
    count.textContent = fmtNumber(open);
    count.dataset.alert = open > 0 ? "true" : "false";
  }
}

function setText(selector, text) {
  const node = qs(selector);
  if (node) node.textContent = text;
}

/* ------------------------------------------------------------------ */
/* Overview                                                           */
/* ------------------------------------------------------------------ */

function renderOverview() {
  const stats = state.stats;
  if (!stats) return;
  const requests = stats.requests || {};
  const byStatus = requests.byStatus || {};
  const risk = stats.risk || {};
  const queues = stats.queues || {};
  setText("#kpiTotal", fmtNumber(requests.total));
  setText("#kpiVerification", fmtNumber(requests.awaitingVerification));
  setText("#kpiHighRisk", fmtNumber(risk.high));
  setText("#kpiDuplicates", fmtNumber(requests.possibleDuplicates));
  setText("#kpiActive", fmtNumber(requests.activeDisasters));
  setText("#kpiApproved", fmtNumber(requests.approved));
  setText("#kpiRejected", fmtNumber(requests.rejected));
  setText("#kpiFlagged", fmtNumber(requests.flagged));

  setText("#queueHighRisk", fmtNumber(queues.high_risk || 0));
  setText("#queueDuplicate", fmtNumber(queues.duplicate_review || 0));
  setText("#queueManual", fmtNumber(queues.manual_review || 0));
  setText("#queueAuto", fmtNumber(queues.auto_approval || 0));

  const riskTotal = (risk.high || 0) + (risk.medium || 0) + (risk.low || 0);
  const pct = (value) => `${riskTotal ? Math.round((value / riskTotal) * 100) : 0}%`;
  setText("#riskHighCount", fmtNumber(risk.high || 0));
  setText("#riskMediumCount", fmtNumber(risk.medium || 0));
  setText("#riskLowCount", fmtNumber(risk.low || 0));
  qs("#riskHighBar").style.width = pct(risk.high || 0);
  qs("#riskMediumBar").style.width = pct(risk.medium || 0);
  qs("#riskLowBar").style.width = pct(risk.low || 0);

  renderResourceGrid(stats.resources || {});
  renderRecentAudit();
  initOverviewMap();
  setText("#tabAll", fmtNumber((queues.high_risk || 0) + (queues.duplicate_review || 0) + (queues.manual_review || 0) + (queues.auto_approval || 0)));
  setText("#tabHighRisk", fmtNumber(queues.high_risk || 0));
  setText("#tabDuplicate", fmtNumber(queues.duplicate_review || 0));
  setText("#tabManual", fmtNumber(queues.manual_review || 0));
  setText("#tabAuto", fmtNumber(queues.auto_approval || 0));

  const approvedish = (byStatus.approved || 0) + (byStatus.resources_assigned || 0);
  setText(
    "#mapNote",
    `${requests.activeDisasters || 0} active incident${requests.activeDisasters === 1 ? "" : "s"} · ${state.centres.length} centres · ${approvedish} approved or allocated. Click an incident to open its review panel.`,
  );
  setText(
    "#mapSummary",
    `${(requests.activeDisasters || 0)} incidents · ${state.centres.length} centres`,
  );
}

function renderResourceGrid(resources) {
  const host = qs("#resourceGrid");
  if (!host) return;
  const available = resources.availableByCategory || {};
  const allocated = resources.allocatedByCategory || {};
  host.innerHTML = `<div class="stack" style="gap:10px">${RESOURCE_ORDER.map((category) => {
    const avail = Number(available[category] || 0);
    const used = Number(allocated[category] || 0);
    const total = avail + used;
    const pct = total ? Math.round((avail / total) * 100) : 0;
    return `<div>
      <div class="between"><span class="small">${esc(resourceLabel(category))}</span>
        <span class="small"><strong>${fmtNumber(avail)}</strong> <span class="muted">available · ${fmtNumber(used)} committed</span></span>
      </div>
      <div class="risk-scale__bar mt-8"><i style="width:${pct}%;background:${pct > 50 ? "var(--ok)" : pct > 20 ? "var(--warn)" : "var(--danger)"}"></i></div>
    </div>`;
  }).join("")}</div>
  <p class="tiny muted mt-16">Centre-level stock. The central reserve is managed in Settings.</p>`;
}

function renderRecentAudit() {
  const host = qs("#recentAudit");
  if (!host) return;
  const rows = state.audit.slice(0, 8);
  if (!rows.length) {
    host.innerHTML = `<div class="table-empty">No audit entries yet.</div>`;
    return;
  }
  host.innerHTML = `<div class="table-wrap"><table class="table table--compact">
    <thead><tr><th>Time</th><th>Action</th><th>Actor</th><th>Request</th><th>Reason / detail</th></tr></thead>
    <tbody>${rows.map((row) => auditRow(row)).join("")}</tbody></table></div>`;
  bindAuditRequestLinks(host);
}

function auditRow(row) {
  return `<tr>
    <td class="nowrap muted">${esc(fmtDateTime(row.createdAt))}<div class="tiny">${esc(fmtRelative(row.createdAt))}</div></td>
    <td><span class="badge badge--neutral">${esc(titleCase(row.action))}</span></td>
    <td>${esc(row.actor || "—")}<div class="tiny muted">${esc(row.role || "")}</div></td>
    <td>${row.requestId ? `<button class="link-button mono" type="button" data-audit-request="${esc(row.requestId)}">${esc(row.requestId)}</button>` : "—"}</td>
    <td class="small">${esc(row.reason || detailSummary(row.details)) || "—"}</td>
  </tr>`;
}

function detailSummary(details) {
  if (!details || typeof details !== "object") return "";
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== "" && !(Array.isArray(value) && !value.length))
    .slice(0, 3)
    .map(([key, value]) => {
      const text = Array.isArray(value)
        ? `${value.length} item${value.length === 1 ? "" : "s"}`
        : typeof value === "object"
          ? JSON.stringify(value)
          : String(value);
      return `${titleCase(key)}: ${text}`;
    })
    .join(" · ");
}

function bindAuditRequestLinks(root) {
  qsa("[data-audit-request]", root).forEach((button) => {
    button.addEventListener("click", () => openRequest(button.dataset.auditRequest));
  });
}

/* ------------------------------------------------------------------ */
/* Request lists                                                      */
/* ------------------------------------------------------------------ */

function wireRequests() {
  qsa("#queueTabs [data-queue]").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.queueFilter = tab.dataset.queue;
      qsa("#queueTabs [data-queue]").forEach((other) => {
        other.setAttribute("aria-selected", String(other === tab));
      });
      renderQueue();
    });
  });
  qs("#queueSearch")?.addEventListener("input", debounce(renderQueue, 200));
  qs("#queueSeverity")?.addEventListener("change", renderQueue);
  qs("#queueSort")?.addEventListener("change", renderQueue);

  qs("#reqSearch")?.addEventListener("input", debounce(renderRequestsView, 200));
  ["#reqStatus", "#reqRisk", "#reqSeverity", "#reqType", "#reqSort"].forEach((selector) => {
    qs(selector)?.addEventListener("change", renderRequestsView);
  });
  qs("#clearFilters")?.addEventListener("click", () => {
    qs("#reqSearch").value = "";
    qs("#reqStatus").value = "";
    qs("#reqRisk").value = "";
    qs("#reqSeverity").value = "";
    qs("#reqType").value = "";
    qs("#reqSort").value = "newest";
    renderRequestsView();
  });

  populateRequestFilters();
}

function populateRequestFilters() {
  const statusSelect = qs("#reqStatus");
  if (statusSelect && statusSelect.options.length <= 1) {
    statusSelect.innerHTML =
      `<option value="">Any status</option>` +
      Object.entries(STATUS_META)
        .map(([key, meta]) => `<option value="${esc(key)}">${esc(meta.label)}</option>`)
        .join("");
  }
  const typeSelect = qs("#reqType");
  if (typeSelect && typeSelect.options.length <= 1) {
    typeSelect.innerHTML =
      `<option value="">Any type</option>` +
      DISASTER_TYPES.map(([value, label]) => `<option value="${value}">${esc(label)}</option>`).join("");
  }
}

function searchableText(request) {
  return [
    request.id,
    request.locationName,
    request.description,
    request.contactName,
    request.contactPhone,
    request.contactEmail,
    request.type,
    request.severity,
    request.workflowStatus,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function sortRequests(list, sort) {
  const copy = [...list];
  if (sort === "oldest") {
    copy.sort((a, b) => new Date(a.submittedAt) - new Date(b.submittedAt));
  } else if (sort === "risk") {
    copy.sort((a, b) => (b.riskScore || 0) - (a.riskScore || 0));
  } else if (sort === "severity") {
    copy.sort(
      (a, b) =>
        (SEVERITY_RANK[b.severity] || 0) - (SEVERITY_RANK[a.severity] || 0) ||
        new Date(b.submittedAt) - new Date(a.submittedAt),
    );
  } else {
    copy.sort((a, b) => new Date(b.submittedAt) - new Date(a.submittedAt));
  }
  return copy;
}

function queuePool() {
  const open = state.requests.filter((request) => OPEN_STATUSES.has(request.workflowStatus));
  if (state.queueFilter === "all") return open;
  return open.filter((request) => request.verificationQueue === state.queueFilter);
}

function renderQueue() {
  const host = qs("#queueTable");
  if (!host) return;
  const search = (qs("#queueSearch")?.value || "").trim().toLowerCase();
  const severity = qs("#queueSeverity")?.value || "";
  const sort = qs("#queueSort")?.value || "oldest";
  let list = queuePool();
  if (search) list = list.filter((request) => searchableText(request).includes(search));
  if (severity) list = list.filter((request) => request.severity === severity);
  list = sortRequests(list, sort);
  setText("#queueMeta", `${list.length} request${list.length === 1 ? "" : "s"} in this queue`);
  setText("#queueHeadCount", `${list.length} waiting`);
  qsa("#queueTabs [data-queue]").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.queue === state.queueFilter));
  });
  const queues = state.stats?.queues || {};
  setText("#tabAll", fmtNumber((queues.high_risk || 0) + (queues.duplicate_review || 0) + (queues.manual_review || 0) + (queues.auto_approval || 0)));
  host.innerHTML = list.length
    ? requestTableHtml(list)
    : `<div class="table-empty">Nothing here. ${state.queueFilter === "all" ? "All incoming reports have been reviewed." : "This queue is clear."}</div>`;
  bindRequestRows(host);
}

function renderRequestsView() {
  const host = qs("#requestTable");
  if (!host) return;
  populateRequestFilters();
  const search = (qs("#reqSearch")?.value || "").trim().toLowerCase();
  const status = qs("#reqStatus")?.value || "";
  const risk = qs("#reqRisk")?.value || "";
  const severity = qs("#reqSeverity")?.value || "";
  const type = qs("#reqType")?.value || "";
  const sort = qs("#reqSort")?.value || "newest";
  let list = state.requests;
  if (search) list = list.filter((request) => searchableText(request).includes(search));
  if (status) list = list.filter((request) => request.workflowStatus === status);
  if (risk) list = list.filter((request) => request.riskLevel === risk);
  if (severity) list = list.filter((request) => request.severity === severity);
  if (type) list = list.filter((request) => request.type === type);
  list = sortRequests(list, sort);
  setText("#requestsMeta", `${list.length} of ${state.requests.length} requests shown`);
  setText("#requestsHeadCount", `${state.requests.length} total`);
  host.innerHTML = list.length
    ? requestTableHtml(list)
    : `<div class="table-empty">No requests match these filters.</div>`;
  bindRequestRows(host);
}

function requestTableHtml(list) {
  return `<div class="table-wrap"><table class="req-table">
    <thead><tr>
      <th scope="col">Request</th>
      <th scope="col">Location</th>
      <th scope="col">Risk</th>
      <th scope="col">Status</th>
      <th scope="col">Queue</th>
      <th scope="col">Submitted</th>
      <th scope="col"><span class="visually-hidden">Open</span></th>
    </tr></thead>
    <tbody>${list.map(requestRowHtml).join("")}</tbody>
  </table></div>`;
}

function requestRowHtml(request) {
  const duplicate = request.duplicateOf
    ? `<div class="req-sub">${icon("merge", 11)} possible duplicate of ${esc(request.duplicateOf)}</div>`
    : "";
  return `<tr data-request="${esc(request.id)}" tabindex="0">
    <td>
      <div class="req-main">${esc(titleCase(request.type))} ${severityBadge(request.severity)}</div>
      <div class="req-id">${esc(request.id)}</div>
      <div class="req-sub">${fmtNumber(request.affectedPeople)} affected</div>
    </td>
    <td>
      <div class="req-loc">${esc(request.locationName)}</div>
      ${duplicate}
    </td>
    <td>${riskBadge(request.riskLevel, request.riskScore)}${request.flagged ? `<div class="req-sub">${icon("flag", 10)} flagged</div>` : ""}</td>
    <td>${statusBadge(request.workflowStatus)}</td>
    <td><span class="tiny muted">${esc(titleCase(request.verificationQueue || "—"))}</span></td>
    <td class="nowrap"><div class="small">${esc(fmtRelative(request.submittedAt))}</div><div class="tiny muted">${esc(fmtDateTime(request.submittedAt))}</div></td>
    <td class="req-actions"><button class="row-open" type="button" tabindex="-1">Open →</button></td>
  </tr>`;
}

function bindRequestRows(root) {
  qsa("[data-request]", root).forEach((row) => {
    row.addEventListener("click", () => openRequest(row.dataset.request));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openRequest(row.dataset.request);
      }
    });
  });
}

/* ------------------------------------------------------------------ */
/* Drawer                                                             */
/* ------------------------------------------------------------------ */

function wireDrawer() {
  qs("#drawerClose")?.addEventListener("click", closeDrawer);
  qs("#drawerBackdrop")?.addEventListener("click", closeDrawer);
  qs("#drawerBody")?.addEventListener("click", handleDrawerAction);
  qs("#drawerFoot")?.addEventListener("click", handleDrawerAction);
}

function closeDrawer() {
  const drawer = qs("#requestDrawer");
  if (!drawer || drawer.hidden) return;
  drawer.hidden = true;
  state.selectedRequest = null;
  state.recommendations = null;
  document.body.style.overflow = "";
  if (lastFocus) lastFocus.focus?.();
}

async function openRequest(id, { keepScroll = false } = {}) {
  const drawer = qs("#requestDrawer");
  if (!drawer) return;
  lastFocus = document.activeElement;
  if (drawer.hidden) {
    state.recommendations = null;
    qs("#drawerBody").innerHTML = `<div class="loading-block"><span class="spinner spinner--dark"></span> Loading request…</div>`;
    qs("#drawerFoot").innerHTML = "";
    qs("#drawerTitle").textContent = "Request";
    qs("#drawerSub").textContent = id;
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
    qs("#drawerClose").focus();
  }
  const scroll = keepScroll ? qs("#drawerBody").scrollTop : 0;
  try {
    const { request } = await api.adminRequest(id);
    state.selectedRequest = request;
    if (state.recommendations?.requestId !== request.id) state.recommendations = null;
    renderDrawer(request);
    qs("#drawerBody").scrollTop = scroll;
  } catch (error) {
    qs("#drawerBody").innerHTML = `<div class="empty"><h3>Request unavailable</h3><p>${esc(error.message)}</p></div>`;
  }
}

function renderDrawer(request) {
  const drawer = qs("#requestDrawer");
  if (!drawer || drawer.hidden) return;
  qs("#drawerTitle").innerHTML = `${esc(titleCase(request.type))} ${severityBadge(request.severity)}`;
  qs("#drawerSub").innerHTML = `<span class="mono">${esc(request.id)}</span> · ${esc(request.locationName)} · submitted ${esc(fmtDateTime(request.submittedAt))}`;
  const body = qs("#drawerBody");
  const scroll = body.scrollTop;
  body.innerHTML = drawerBodyHtml(request);
  qs("#drawerFoot").innerHTML = drawerFootHtml(request);
  body.scrollTop = scroll;
  bindDrawerEvidence();
}

function drawerBodyHtml(request) {
  const risk = request.risk || {};
  const reasons = Array.isArray(risk.reasons) ? risk.reasons : [];
  const checks = Array.isArray(risk.checks) ? risk.checks : [];
  const duplicates = request.duplicates || [];
  const allocations = request.allocations || [];
  const needsApproval = OPEN_STATUSES.has(request.workflowStatus);
  const showRecommendations = ALLOCATABLE.has(request.workflowStatus);

  const duplicateSection = duplicates.length
    ? `<div class="drawer-section">
        <p class="drawer-section__title">Duplicate analysis <span class="badge badge--purple">${duplicates.length} match${duplicates.length === 1 ? "" : "es"}</span></p>
        ${request.duplicateOf ? `<div class="notice" style="background:#fcfbff;border-color:#d9d6fe;color:#4a1fb8">
          ${icon("merge", 16)}<span>Flagged as a possible duplicate of <span class="mono">${esc(request.duplicateOf)}</span>. A person must merge, link or keep it separate.</span>
        </div>` : ""}
        ${duplicates.map((match) => duplicateCardHtml(match, request)).join("")}
      </div>`
    : `<div class="drawer-section">
        <p class="drawer-section__title">Duplicate analysis</p>
        <div class="notice notice--ok">${icon("check", 16)}<span>No recent report is similar enough to flag as a duplicate. Threshold: ${esc(request.risk?.thresholds?.duplicate || state.settings?.duplicateThreshold || 60)}/100 within ${esc(state.settings?.duplicateWindowHours || 72)} hours.</span></div>
      </div>`;

  return `
    <div class="flex flex-wrap" style="gap:6px">
      ${statusBadge(request.workflowStatus, { large: true })}
      ${riskBadge(request.riskLevel, request.riskScore)}
      ${request.flagged ? `<span class="badge badge--danger">${icon("flag", 11)} Flagged</span>` : ""}
      ${request.mergedInto ? `<span class="badge badge--purple">Merged into ${esc(request.mergedInto)}</span>` : ""}
      ${request.linkedTo?.length ? `<span class="badge badge--neutral">${icon("link", 11)} Linked to ${esc(request.linkedTo.join(", "))}</span>` : ""}
      ${request.isDemo ? `<span class="badge badge--warn">Demo data</span>` : ""}
    </div>

    <div class="drawer-section">
      <p class="drawer-section__title">Verification &amp; risk
        <span class="badge risk" data-risk="${esc(request.riskLevel)}">${esc(titleCase(request.riskLevel))} · ${esc(request.riskScore)}/100</span>
      </p>
      <div class="risk-hero">
        <div class="risk-hero__score">${esc(request.riskScore)}<small>/100</small></div>
        <div class="risk-scale">
          <div class="risk-scale__bar"><i style="width:${Math.max(2, Number(request.riskScore) || 0)}%;background:${request.riskLevel === "high" ? "var(--danger)" : request.riskLevel === "medium" ? "var(--warn)" : "var(--ok)"}"></i></div>
          <div class="risk-scale__labels"><span>Low</span><span>Medium</span><span>High</span></div>
        </div>
      </div>
      ${request.autoDecision ? `<div class="notice notice--info">${icon("info", 16)}<span><strong>Why it is here:</strong> ${esc(request.autoDecision)}</span></div>` : ""}
      <div class="factor-list">
        ${
          reasons.length
            ? reasons
                .map(
                  (reason) => `<div class="factor">
                    <div class="factor__body"><strong>${esc(reason.label)}</strong><span>${esc(reason.detail)}</span></div>
                    <span class="factor__points">+${esc(reason.points)}</span>
                  </div>`,
                )
                .join("")
            : `<div class="factor factor--ok"><div class="factor__body"><strong>No risk signals</strong><span>Every automated check reported nothing unusual.</span></div><span class="factor__points factor__points--zero">0</span></div>`
        }
      </div>
      ${
        checks.length
          ? `<details>
              <summary class="small muted" style="cursor:pointer;margin-top:2px">Show all ${checks.length} checks</summary>
              <div class="checks">${checks
                .map(
                  (check) => `<div class="check-row check-row--${check.status === "ok" ? "ok" : check.status === "info" ? "info" : "warn"}">
                    ${icon(check.status === "ok" ? "check-circle" : "info", 14)}
                    <span><strong>${esc(check.label)}:</strong> ${esc(check.detail)}</span>
                  </div>`,
                )
                .join("")}</div>
            </details>`
          : ""
      }
      <p class="tiny muted">Risk scoring is advisory only. It can never reject or discard a report.</p>
    </div>

    ${duplicateSection}

    <div class="drawer-section">
      <p class="drawer-section__title">Reported details</p>
      <p class="detail-desc">${esc(request.description || "No description was supplied.")}</p>
      <div class="detail-grid">
        <div class="detail-item"><span>Affected people</span><strong>${fmtNumber(request.affectedPeople)}</strong></div>
        <div class="detail-item"><span>Severity</span>${severityBadge(request.severity)}</div>
        <div class="detail-item"><span>Location</span><strong>${esc(request.locationName)}</strong><div class="tiny muted mono">${Number(request.latitude).toFixed(5)}, ${Number(request.longitude).toFixed(5)}</div></div>
        <div class="detail-item"><span>Contact</span>
          ${request.contactName ? `<strong>${esc(request.contactName)}</strong>` : `<span class="muted">Not supplied</span>`}
          <div class="small">
            ${request.contactPhone ? `<a href="tel:${esc(request.contactPhone.replaceAll(" ", ""))}">${esc(request.contactPhone)}</a>` : ""}
            ${request.contactPhone && request.contactEmail ? " · " : ""}
            ${request.contactEmail ? `<a href="mailto:${esc(request.contactEmail)}">${esc(request.contactEmail)}</a>` : ""}
          </div>
        </div>
        <div class="detail-item"><span>Resources requested</span><strong>${esc(itemsSummary(request.resourceQuantities))}</strong>
          <div class="tiny muted">${esc((request.requiredResources || []).map(resourceLabel).join(" · ") || "None specified")}</div>
        </div>
        <div class="detail-item"><span>Resource guarantee</span><strong>${esc(itemsSummary(request.grantedResources))}</strong><div class="tiny muted">Promise made at submission time</div></div>
      </div>
      ${request.infoRequested ? `<div class="notice notice--warn">${icon("alert", 16)}<span><strong>Information requested:</strong> ${esc(request.infoRequested)}</span></div>` : ""}
      ${request.decisionMessage ? `<div class="notice ${request.workflowStatus === "rejected" ? "notice--danger" : "notice--ok"}">${icon(request.workflowStatus === "rejected" ? "x-circle" : "check-circle", 16)}<span><strong>Decision message sent to the reporter:</strong><br>${esc(request.decisionMessage)}</span></div>` : ""}
      <div class="btn-row">
        <button class="btn btn--ghost btn--sm" type="button" data-action="show-map">${icon("map", 15)} Show on map</button>
      </div>
    </div>

    <div class="drawer-section">
      <p class="drawer-section__title">Supporting evidence ${request.evidence?.length ? `<span class="badge badge--neutral">${request.evidence.length}</span>` : ""}</p>
      ${
        request.evidence?.length
          ? `<div class="evidence-list">${request.evidence
              .map(
                (file) => `<a class="evidence-chip" href="${esc(file.url)}" target="_blank" rel="noopener" style="text-decoration:none">
                  ${file.mimeType === "application/pdf" ? icon("file", 22) : `<img src="${esc(file.url)}" alt="" loading="lazy">`}
                  <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:170px">${esc(file.originalName)}</span>
                  <span class="tiny muted">${esc(fmtBytes(file.sizeBytes))}</span>
                </a>`,
              )
              .join("")}</div>
            <p class="tiny muted">Byte-identical files reused on another request are flagged by the risk engine.</p>`
          : `<p class="small muted">No files attached.</p>`
      }
    </div>

    ${
      showRecommendations
        ? `<div class="drawer-section" id="allocationSection">
            <p class="drawer-section__title">Resource allocation
              <button class="btn btn--secondary btn--sm" type="button" data-action="recommend">${icon("truck", 15)} ${state.recommendations?.requestId === request.id ? "Refresh recommendations" : "Find best resources"}</button>
            </p>
            ${allocationPanelHtml(request)}
          </div>`
        : `<div class="drawer-section">
            <p class="drawer-section__title">Resource allocation</p>
            <div class="notice">${icon("info", 16)}<span>Approve this request to unlock nearest-centre recommendations and dispatch.</span></div>
          </div>`
    }

    <div class="drawer-section">
      <p class="drawer-section__title">Audit trail <span class="badge badge--neutral">${(request.audit || []).length}</span></p>
      <ul class="timeline timeline--muted">
        ${(request.audit || [])
          .slice()
          .reverse()
          .slice(0, 14)
          .map(
            (entry) => `<li>
              <div class="timeline__time">${esc(fmtDateTime(entry.createdAt))} · ${esc(entry.actor || "system")}${entry.role ? ` (${esc(entry.role)})` : ""}</div>
              <div class="timeline__text"><strong>${esc(titleCase(entry.action))}</strong>${entry.reason ? ` — ${esc(entry.reason)}` : ""}</div>
            </li>`,
          )
          .join("") || `<li><div class="timeline__text muted">No audit entries.</div></li>`}
      </ul>
      <p class="tiny muted">Records who acted, when, and the reason. Append-only by design.</p>
    </div>
  `;
}

function duplicateCardHtml(match, request) {
  return `<div class="duplicate">
    <div class="duplicate__top">
      <div>
        <span class="duplicate__id">${esc(match.id)}</span>
        <div class="small">${esc(match.locationName || "Unknown location")} · ${fmtDistance(match.distanceKm)} away</div>
        <div class="tiny muted">${esc(titleCase(match.type))} · ${esc(match.status ? titleCase(match.status) : "reported")} · ${esc(fmtDateTime(match.submittedAt))}</div>
      </div>
      <span class="duplicate__score">${esc(match.similarity)}% match</span>
    </div>
    <div class="duplicate__factors">
      ${(match.factors || []).map((factor) => `<span>${esc(factor.label)} +${esc(factor.points)}</span>`).join("")}
      <span>${esc(match.descriptionSimilarity)}% wording</span>
      ${match.contactMatch ? "<span>same contact</span>" : ""}
    </div>
    ${request.workflowStatus === "possible_duplicate"
      ? `<div class="duplicate__actions">
          <button class="btn btn--secondary btn--sm" type="button" data-action="merge" data-target="${esc(match.id)}">${icon("merge", 14)} Merge into ${esc(match.id)}</button>
          <button class="btn btn--ghost btn--sm" type="button" data-action="link" data-target="${esc(match.id)}">${icon("link", 14)} Link</button>
          <button class="btn btn--ghost btn--sm" type="button" data-action="keep-separate">Keep separate</button>
        </div>`
      : `<div class="duplicate__actions">
          <button class="btn btn--ghost btn--sm" type="button" data-action="open-target" data-target="${esc(match.id)}">Open ${esc(match.id)}</button>
          <button class="btn btn--ghost btn--sm" type="button" data-action="link" data-target="${esc(match.id)}">${icon("link", 14)} Link</button>
        </div>`}
  </div>`;
}

function allocationPanelHtml(request) {
  const recommendations = state.recommendations?.requestId === request.id ? state.recommendations : null;
  const allocations = request.allocations || [];
  const allocationsHtml = allocations.length
    ? `<div class="stack" style="gap:8px">
        ${allocations
          .map(
            (allocation) => `<div class="allocation-row">
              <div class="allocation-row__top">
                <strong style="font-size:0.83rem">${esc(allocation.centreId)}</strong>
                <span class="badge badge--neutral">${esc(titleCase(allocation.status))}</span>
              </div>
              <div class="allocation-row__items">${esc(itemsSummary(allocation.items))}</div>
              <div class="tiny muted">${allocation.distanceKm ? `${fmtDistance(allocation.distanceKm)} · ${fmtDuration(allocation.durationMin)}${allocation.distanceSource === "estimate" ? " (estimated)" : ""}` : "No distance recorded"} · ${esc(fmtDateTime(allocation.createdAt))}</div>
              ${allocation.overrideReason ? `<div class="tiny text-warn">Override: ${esc(allocation.overrideReason)}</div>` : ""}
              <div class="allocation-actions">
                ${allocation.status === "assigned" ? `<button class="btn btn--secondary btn--sm" type="button" data-action="allocation-status" data-allocation="${esc(allocation.id)}" data-status="dispatched">${icon("truck", 14)} Dispatched</button>` : ""}
                ${["assigned", "dispatched"].includes(allocation.status) ? `<button class="btn btn--ghost btn--sm" type="button" data-action="allocation-status" data-allocation="${esc(allocation.id)}" data-status="delivered">${icon("check", 14)} Delivered</button>` : ""}
                ${["assigned", "dispatched"].includes(allocation.status) ? `<button class="btn btn--danger-soft btn--sm" type="button" data-action="allocation-status" data-allocation="${esc(allocation.id)}" data-status="cancelled">Cancel</button>` : ""}
              </div>
            </div>`,
          )
          .join("")}
      </div>`
    : `<p class="small muted">No resources committed yet.</p>`;

  if (!recommendations) {
    return `${allocationsHtml}
      <div class="notice notice--info">${icon("truck", 16)}<span>Recommendations compare road distance, travel time, live centre stock, availability and existing commitments. Stock is only committed when you confirm.</span></div>`;
  }

  const plan = recommendations.plan || [];
  return `${allocationsHtml}
    <div class="notice ${plan.length ? "notice--ok" : "notice--warn"}">
      ${icon(plan.length ? "check-circle" : "alert", 16)}
      <span><strong>${plan.length ? "Suggested plan covers " + recommendations.coveredPct + "% of the request." : "No single centre can cover this request."}</strong>
      ${plan.length ? " " + plan.map((entry) => `${esc(entry.name)}: ${esc(itemsSummary(entry.items))}`).join("; ") + "." : " Adjust the request or restock a centre."}
      ${recommendations.uncovered && Object.keys(recommendations.uncovered).length ? ` Uncovered: ${esc(itemsSummary(recommendations.uncovered))}.` : ""}</span>
    </div>
    <div class="stack" style="gap:8px">
      ${recommendations.candidates
        .map(
          (candidate, index) => `<div class="candidate ${index === 0 ? "is-top" : ""}">
            <div class="candidate__top">
              <div>
                <div class="candidate__name">${index === 0 ? `<span class="badge badge--ok" style="margin-right:6px">Best match</span>` : ""}${esc(candidate.name)}</div>
                <div class="candidate__meta">${esc(titleCase(candidate.category))} · ${esc(candidate.address || "")}</div>
              </div>
              <div class="candidate__score">${esc(candidate.score)}<div class="tiny muted" style="text-align:right">score</div></div>
            </div>
            <div class="candidate__stats">
              <span class="candidate__stat">${icon("nav", 12)} <b>${fmtDistance(candidate.distanceKm)}</b> ${candidate.distanceSource === "osrm" ? "routed" : "estimated"}</span>
              <span class="candidate__stat">${icon("clock", 12)} <b>${fmtDuration(candidate.durationMin)}</b></span>
              <span class="candidate__stat">${icon("check-circle", 12)} <b>${esc(candidate.coveragePct)}%</b> cover</span>
              <span class="candidate__stat">${availabilityBadge(candidate.availability)}</span>
            </div>
            <div class="candidate__factors">${(candidate.factors || []).map((factor) => `<span>${esc(factor.label)} ${esc(factor.points)}</span>`).join("")}</div>
            ${candidate.warnings?.length ? `<div class="candidate__warn">${candidate.warnings.map((warning) => esc(warning)).join(" ")}</div>` : ""}
            <div class="btn-row">
              <button class="btn ${index === 0 ? "btn--primary" : "btn--secondary"} btn--sm" type="button" data-action="allocate" data-centre="${esc(candidate.centreId)}" ${Object.keys(candidate.supplied || {}).length ? "" : "disabled"}>
                ${icon("truck", 14)} Assign from this centre
              </button>
              <span class="tiny muted">${esc(stockSummary(candidate.stock))}</span>
            </div>
          </div>`,
        )
        .join("")}
    </div>
    <p class="tiny muted">${esc(recommendations.note || "")} Distances are ${recommendations.candidates.some((item) => item.distanceSource === "osrm") ? "road distances from OSRM" : "labelled estimates because routing was unavailable"}.</p>`;
}

function drawerFootHtml(request) {
  const status = request.workflowStatus;
  const canDecide = OPEN_STATUSES.has(status);
  return `
    ${canDecide ? `<button class="btn btn--ok btn--sm" type="button" data-action="approve">${icon("check", 15)} Approve</button>` : ""}
    ${canDecide ? `<button class="btn btn--danger-soft btn--sm" type="button" data-action="reject">${icon("x", 15)} Reject</button>` : ""}
    ${canDecide ? `<button class="btn btn--secondary btn--sm" type="button" data-action="request-info">${icon("info", 15)} Request info</button>` : ""}
    ${status === "possible_duplicate" ? `<button class="btn btn--secondary btn--sm" type="button" data-action="keep-separate">${icon("merge", 15)} Keep separate</button>` : ""}
    ${["resources_assigned"].includes(status) ? `<button class="btn btn--primary btn--sm" type="button" data-action="start">${icon("truck", 15)} Start response</button>` : ""}
    ${["in_progress", "resources_assigned"].includes(status) ? `<button class="btn btn--primary btn--sm" type="button" data-action="resolve">${icon("check-circle", 15)} Mark resolved</button>` : ""}
    ${!canDecide ? `<button class="btn btn--secondary btn--sm" type="button" data-action="flag">${icon("flag", 15)} Flag for follow-up</button>` : ""}
    <span style="flex:1"></span>
    <button class="btn btn--ghost btn--sm" type="button" data-action="close">Close</button>
  `;
}

function bindDrawerEvidence() {
  // Evidence links are plain anchors; nothing to wire. Kept as a seam.
}

async function handleDrawerAction(event) {
  const trigger = event.target.closest("[data-action]");
  if (!trigger) return;
  const action = trigger.dataset.action;
  const request = state.selectedRequest;
  if (!request) return;

  if (action === "close") return closeDrawer();
  if (action === "show-map") {
    closeDrawer();
    showView("map");
    setTimeout(() => maps.operations?.focus(request.latitude, request.longitude, 14), 250);
    return;
  }
  if (action === "open-target") {
    const target = trigger.dataset.target;
    state.recommendations = null;
    return openRequest(target);
  }
  if (action === "recommend") {
    return loadRecommendations(request);
  }
  if (action === "allocate") {
    return openAllocationDialog(request, trigger.dataset.centre);
  }
  if (action === "allocation-status") {
    return updateAllocation(trigger.dataset.allocation, trigger.dataset.status);
  }
  if (action === "approve") {
    return openDialog({
      title: "Approve this request",
      intro: "Approval makes the request eligible for resource allocation. The reporter is notified.",
      fields: [
        {
          type: "textarea",
          name: "message",
          label: "Message to the reporter (optional)",
          placeholder: "e.g. Approved. A medical team is being assigned from Doon District Hospital.",
        },
      ],
      confirmLabel: "Approve request",
      tone: "ok",
      onConfirm: async (values) => {
        await api.action(request.id, { action: "approve", message: values.message || undefined });
        toast("Request approved", request.id, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "reject") {
    return openDialog({
      title: "Reject this request",
      intro: "A rejection is permanent for this request and requires a reason. Use Request info if you need more detail first.",
      fields: [
        {
          type: "textarea",
          name: "reason",
          label: "Reason for rejection",
          required: true,
          placeholder: "e.g. Duplicate of an ongoing operation already covering this zone.",
        },
        {
          type: "textarea",
          name: "message",
          label: "Message to the reporter (optional)",
          placeholder: "Defaults to the standard rejection message if left blank.",
        },
      ],
      confirmLabel: "Reject request",
      tone: "danger",
      onConfirm: async (values) => {
        await api.action(request.id, {
          action: "reject",
          reason: values.reason,
          message: values.message || undefined,
        });
        toast("Request rejected", `${request.id} · reason recorded`, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "request-info") {
    return openDialog({
      title: "Request more information",
      intro: "The request moves to Under verification and the reporter sees your message.",
      fields: [
        {
          type: "textarea",
          name: "reason",
          label: "What do you need?",
          required: true,
          placeholder: "e.g. Please confirm the number of families and whether the road is accessible.",
        },
      ],
      confirmLabel: "Send request",
      onConfirm: async (values) => {
        await api.action(request.id, { action: "request_info", reason: values.reason });
        toast("Information requested", request.id, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "flag") {
    return openDialog({
      title: "Flag for follow-up",
      intro: "Flagging is internal. It does not change the request status.",
      fields: [
        {
          type: "textarea",
          name: "reason",
          label: "Why flag this request?",
          required: true,
          placeholder: "e.g. Caller unreachable; verify through the ward office.",
        },
      ],
      confirmLabel: "Flag request",
      async onConfirm(values) {
        await api.action(request.id, { action: "flag", reason: values.reason });
        toast("Request flagged", request.id, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "merge") {
    const target = trigger.dataset.target;
    return openDialog({
      title: `Merge into ${target}`,
      intro: "This request will be closed as a duplicate and linked to the surviving report. Information is preserved in the audit log.",
      fields: [
        {
          type: "textarea",
          name: "reason",
          label: "Reason (optional)",
          placeholder: "e.g. Same incident, same contact, 70 m apart.",
        },
      ],
      confirmLabel: "Merge and close",
      tone: "danger",
      onConfirm: async (values) => {
        await api.action(request.id, { action: "merge", targetId: target, reason: values.reason || undefined });
        toast("Requests merged", `${request.id} → ${target}`, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "link") {
    const target = trigger.dataset.target || "";
    return openDialog({
      title: "Link related reports",
      intro: "Linking keeps both reports open and records the relationship.",
      fields: [
        { type: "input", name: "targetId", label: "Related request ID", value: target, required: true, placeholder: "REQ-…" },
        { type: "textarea", name: "reason", label: "Note (optional)" },
      ],
      confirmLabel: "Link reports",
      onConfirm: async (values) => {
        await api.action(request.id, { action: "link", targetId: values.targetId, reason: values.reason || undefined });
        toast("Reports linked", `${request.id} ↔ ${values.targetId}`, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "keep-separate") {
    return openDialog({
      title: "Keep this report separate",
      intro: "Confirms this is a distinct incident. It returns to the approval queue and is no longer flagged as a duplicate.",
      fields: [
        { type: "textarea", name: "reason", label: "Note (optional)", placeholder: "e.g. Different village on the same road." },
      ],
      confirmLabel: "Keep separate",
      onConfirm: async (values) => {
        await api.action(request.id, { action: "keep_separate", reason: values.reason || undefined });
        toast("Kept as a separate incident", request.id, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "start") {
    return confirmAction({
      title: "Start the response?",
      intro: "Marks the request In progress so the reporter sees that relief is on the way.",
      confirmLabel: "Start response",
      run: async () => {
        await api.action(request.id, { action: "start" });
        toast("Response started", request.id, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
  if (action === "resolve") {
    return openDialog({
      title: "Mark as resolved",
      intro: "Closes the response. Use this only after relief has been delivered and the reporter has been updated.",
      fields: [{ type: "textarea", name: "reason", label: "Closing note (optional)" }],
      confirmLabel: "Mark resolved",
      onConfirm: async (values) => {
        await api.action(request.id, { action: "resolve", reason: values.reason || undefined });
        toast("Request resolved", request.id, "ok");
        await refreshAll({ quiet: true });
      },
    });
  }
}

async function loadRecommendations(request) {
  const section = qs("#allocationSection");
  if (section) {
    section.innerHTML = `<p class="drawer-section__title">Resource allocation</p><div class="loading-block"><span class="spinner spinner--dark"></span> Comparing centres, stock and road distance…</div>`;
  }
  try {
    const data = await api.recommendations(request.id);
    state.recommendations = { ...data, requestId: request.id };
    renderDrawer(state.selectedRequest);
    qs("#allocationSection")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    toast("Recommendations unavailable", error.message, "error");
    renderDrawer(state.selectedRequest);
  }
}

function openAllocationDialog(request, centreId) {
  const candidate = (state.recommendations?.candidates || []).find((item) => item.centreId === centreId);
  if (!candidate) {
    toast("Centre not found", "Re-run the recommendations and try again.", "error");
    return;
  }
  const top = state.recommendations?.candidates?.[0]?.centreId;
  const isOverride = candidate.centreId !== top;
  const stock = candidate.stock || {};
  const supplied = candidate.supplied || {};
  const requested = state.recommendations?.requested || {};
  const fields = Object.entries(supplied).length
    ? Object.entries(supplied).map(([category, amount]) => ({
        type: "number",
        name: `qty_${category}`,
        label: `${resourceLabel(category)} to allocate (max ${stock[category] ?? amount}; requested ${requested[category] ?? amount})`,
        value: String(amount),
        min: 1,
        max: Math.min(Number(stock[category] ?? amount), Number(requested[category] ?? amount)),
      }))
    : [];
  if (isOverride) {
    fields.push({
      type: "textarea",
      name: "overrideReason",
      label: "Override reason (required)",
      required: true,
      placeholder: "Explain why this centre is being chosen over the top recommendation.",
    });
  }
  openDialog({
    title: `Assign resources from ${candidate.name}`,
    intro: `${fmtDistance(candidate.distanceKm)} · ${fmtDuration(candidate.durationMin)} · ${candidate.distanceSource === "estimate" ? "estimated road distance" : "routed road distance"} · ${candidate.coveragePct}% coverage. Stock is deducted immediately.`,
    fields,
    confirmLabel: "Commit allocation",
    tone: "ok",
    onConfirm: async (values) => {
      const items = {};
      Object.entries(supplied).forEach(([category]) => {
        const qty = Number(values[`qty_${category}`] || 0);
        if (qty > 0) items[category] = Math.trunc(qty);
      });
      if (!Object.keys(items).length) throw new Error("Choose at least one resource quantity.");
      await api.allocate(request.id, {
        centreId: candidate.centreId,
        items,
        overrideReason: values.overrideReason || undefined,
        distance: {
          distanceKm: candidate.distanceKm,
          durationMin: candidate.durationMin,
          distanceSource: candidate.distanceSource,
          factors: candidate.factors,
        },
      });
      toast("Resources allocated", `${itemsSummary(items)} from ${candidate.name}`, "ok");
      state.recommendations = null;
      await refreshAll({ quiet: true });
      await openRequest(request.id, { keepScroll: true });
    },
  });
}

async function updateAllocation(id, status) {
  try {
    await api.updateAllocation(id, { status });
    toast("Allocation updated", `${id} → ${titleCase(status)}`, "ok");
    state.recommendations = null;
    await refreshAll({ quiet: true });
  } catch (error) {
    toast("Could not update allocation", error.message, "error");
  }
}

/* ------------------------------------------------------------------ */
/* Maps                                                               */
/* ------------------------------------------------------------------ */

function wireMaps() {
  qsa("#mapFilters [data-layer]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const layer = chip.dataset.layer;
      const active = chip.getAttribute("aria-pressed") === "true";
      chip.setAttribute("aria-pressed", String(!active));
      chip.classList.toggle("is-active", !active);
      if (active) state.adminMapLayers.delete(layer);
      else state.adminMapLayers.add(layer);
      renderOperationsMap();
    });
  });
  const legend = qs("#adminMapLegend");
  if (legend) {
    legend.innerHTML = Object.entries(CATEGORY_META)
      .filter(([key]) => key !== "user")
      .map(
        ([key, meta]) =>
          `<span><i style="background:${meta.color}"></i>${esc(meta.label)}</span>`,
      )
      .join("");
  }
}

function mapIncidents() {
  return state.requests.filter((request) =>
    ["approved", "resources_assigned", "in_progress", "under_verification", "possible_duplicate", "awaiting_approval", "submitted"].includes(
      request.workflowStatus,
    ),
  );
}

function renderOperationsMap() {
  const element = qs("#adminMap");
  if (!element) return;
  if (!maps.operations) {
    maps.operations = new DrrasMap(element, { zoom: 11 });
  }
  const map = maps.operations;
  if (!map.ready) return;
  const incidents = mapIncidents();
  map.setIncidents(state.adminMapLayers.has("incident") ? incidents : [], {
    onClick: (incident) => openRequest(incident.id),
  });
  const centres = state.centres.filter((centre) => state.adminMapLayers.has(centre.category));
  map.setCentres(centres, {
    onClick: (centre) => {
      toast(centre.name, `${titleCase(centre.category)} · ${centre.availability} · ${centre.phone || "no phone"}`, "info");
    },
  });
  const activeCount = incidents.filter((request) => ["approved", "resources_assigned", "in_progress"].includes(request.workflowStatus)).length;
  setText("#adminMapSummary", `${activeCount} active · ${incidents.length} open · ${centres.length} centres shown`);
  const points = [
    ...incidents.map((request) => [request.latitude, request.longitude]),
    ...centres.map((centre) => [centre.latitude, centre.longitude]),
  ];
  if (points.length) map.fit(points, { maxZoom: 12, padding: [30, 30] });
}

function initOverviewMap() {
  const element = qs("#adminOverviewMap");
  if (!element) return;
  if (!maps.overview) maps.overview = new DrrasMap(element, { zoom: 11 });
  const map = maps.overview;
  if (!map.ready) return;
  map.invalidate();
  map.setIncidents(mapIncidents(), { onClick: (incident) => openRequest(incident.id) });
  map.setCentres(state.centres, {
    onClick: (centre) => toast(centre.name, `${titleCase(centre.category)} · ${centre.availability}`, "info"),
  });
  const points = [
    ...mapIncidents().map((request) => [request.latitude, request.longitude]),
    ...state.centres.map((centre) => [centre.latitude, centre.longitude]),
  ];
  if (points.length) map.fit(points, { maxZoom: 12, padding: [30, 30] });
}

/* ------------------------------------------------------------------ */
/* Centres                                                            */
/* ------------------------------------------------------------------ */

function wireCentres() {
  qs("#centreSearch")?.addEventListener("input", debounce(() => {
    state.centresFilter.search = qs("#centreSearch").value.trim().toLowerCase();
    renderCentres();
  }, 180));
  qs("#centreCategoryFilter")?.addEventListener("change", () => {
    state.centresFilter.category = qs("#centreCategoryFilter").value;
    renderCentres();
  });
  qs("#addCentreButton")?.addEventListener("click", () => openCentreDialog(null));
  qs("#centreTable")?.addEventListener("click", (event) => {
    const edit = event.target.closest("[data-edit-centre]");
    if (edit) openCentreDialog(edit.dataset.editCentre);
  });
  populateCentreCategories();
  qs("#centreForm")?.addEventListener("submit", saveCentreDialog);
  qs("#centreCancel")?.addEventListener("click", () => qs("#centreDialog").close());
  wireCentreStockFields();
}

function populateCentreCategories() {
  const fields = qs("#centreCategory");
  const filter = qs("#centreCategoryFilter");
  if (fields && !fields.options.length) {
    fields.innerHTML = Object.entries(CATEGORY_META)
      .filter(([key]) => key !== "incident" && key !== "user")
      .map(([key, meta]) => `<option value="${key}">${esc(meta.label)}</option>`)
      .join("");
  }
  if (filter && filter.options.length <= 1) {
    filter.innerHTML =
      `<option value="">All categories</option>` +
      Object.entries(CATEGORY_META)
        .filter(([key]) => key !== "incident" && key !== "user")
        .map(([key, meta]) => `<option value="${key}">${esc(meta.label)}</option>`)
        .join("");
  }
}

function wireCentreStockFields() {
  const host = qs("#centreStockFields");
  if (!host || host.children.length) return;
  host.innerHTML = RESOURCE_ORDER.map(
    (category) => `<div class="field"><label for="stock_${category}">${esc(resourceLabel(category))}</label>
      <input class="input" id="stock_${category}" data-stock="${category}" type="number" min="0" step="1" value="0"></div>`,
  ).join("");
}

function renderCentres() {
  const host = qs("#centreTable");
  if (!host) return;
  populateCentreCategories();
  const { search, category } = state.centresFilter;
  let list = state.centres;
  if (search) {
    list = list.filter((centre) =>
      [centre.name, centre.address, centre.category, centre.phone].filter(Boolean).join(" ").toLowerCase().includes(search),
    );
  }
  if (category) list = list.filter((centre) => centre.category === category);
  setText("#centreMeta", `${list.length} of ${state.centres.length} centres`);
  const admin = state.role === "admin";
  host.innerHTML = `<div class="table-wrap"><table class="table">
    <thead><tr><th>Centre</th><th>Contact</th><th>Availability</th><th>Stock on hand</th><th>Updated</th>${admin ? `<th></th>` : ""}</tr></thead>
    <tbody>${list
      .map(
        (centre) => `<tr>
          <td>
            <div class="strong">${esc(centre.name)}</div>
            <div class="sub">${esc(titleCase(centre.category))} · ${esc(centre.address || "No address")}</div>
          </td>
          <td class="small">${centre.phone ? `<a href="tel:${esc(centre.phone.replaceAll(" ", ""))}">${esc(centre.phone)}</a>` : "—"}</td>
          <td>${availabilityBadge(centre.availability)}</td>
          <td class="small">${esc(stockSummary(centre.stock))}</td>
          <td class="small muted nowrap">${esc(fmtRelative(centre.updatedAt))}</td>
          ${admin ? `<td class="right"><button class="row-open" type="button" data-edit-centre="${esc(centre.id)}">${icon("edit", 12)} Edit</button></td>` : ""}
        </tr>`,
      )
      .join("") || `<tr><td colspan="6" class="table-empty">No centres match this filter.</td></tr>`}</tbody>
  </table></div>`;
}

function openCentreDialog(centreId) {
  if (state.role !== "admin") {
    toast("Read-only role", "Only administrators can edit help centres.", "error");
    return;
  }
  const centre = centreId ? state.centres.find((item) => item.id === centreId) : null;
  state.centreEditingId = centreId || null;
  qs("#centreDialogTitle").textContent = centre ? `Edit ${centre.name}` : "Add a help centre";
  populateCentreCategories();
  wireCentreStockFields();
  qs("#centreName").value = centre?.name || "";
  qs("#centreCategory").value = centre?.category || "hospital";
  qs("#centreAvailability").value = centre?.availability || "available";
  qs("#centreAddress").value = centre?.address || "";
  qs("#centrePhone").value = centre?.phone || "";
  qs("#centreCapacity").value = centre?.capacityNote || "";
  qs("#centreLat").value = centre?.latitude ?? 30.3165;
  qs("#centreLon").value = centre?.longitude ?? 78.0322;
  qsa("[data-stock]").forEach((input) => {
    input.value = centre?.stock?.[input.dataset.stock] ?? 0;
  });
  qs("#centreDialogError").textContent = "";
  qs("#centreDialog").showModal();
}

async function saveCentreDialog(event) {
  event.preventDefault();
  const button = qs("#centreSave");
  const error = qs("#centreDialogError");
  error.textContent = "";
  const stock = {};
  qsa("[data-stock]").forEach((input) => {
    stock[input.dataset.stock] = Number(input.value || 0);
  });
  const payload = {
    name: qs("#centreName").value.trim(),
    category: qs("#centreCategory").value,
    availability: qs("#centreAvailability").value,
    address: qs("#centreAddress").value.trim(),
    phone: qs("#centrePhone").value.trim(),
    capacityNote: qs("#centreCapacity").value.trim(),
    latitude: Number(qs("#centreLat").value),
    longitude: Number(qs("#centreLon").value),
    stock,
  };
  if (!payload.name) {
    error.textContent = "Enter a centre name.";
    return;
  }
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Saving…";
  try {
    if (state.centreEditingId) {
      await api.updateCentre(state.centreEditingId, payload);
      toast("Centre updated", payload.name, "ok");
    } else {
      await api.createCentre(payload);
      toast("Centre added", payload.name, "ok");
    }
    qs("#centreDialog").close();
    await refreshAll({ quiet: true });
  } catch (err) {
    error.textContent = err.message;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

/* ------------------------------------------------------------------ */
/* Audit                                                              */
/* ------------------------------------------------------------------ */

function wireAudit() {
  qs("#auditSearch")?.addEventListener("input", debounce(renderAudit, 180));
  qs("#auditLimit")?.addEventListener("change", async (event) => {
    state.auditLimit = Number(event.target.value);
    try {
      const { audit } = await api.adminAudit({ limit: state.auditLimit });
      state.audit = audit || [];
      renderAudit();
    } catch (error) {
      toast("Audit log unavailable", error.message, "error");
    }
  });
}

function renderAudit() {
  const host = qs("#auditTable");
  if (!host) return;
  const search = (qs("#auditSearch")?.value || "").trim().toLowerCase();
  let rows = state.audit;
  if (search) {
    rows = rows.filter((row) =>
      [row.action, row.actor, row.role, row.requestId, row.reason, detailSummary(row.details)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(search),
    );
  }
  setText("#auditMeta", `${rows.length} entries`);
  setText("#auditHeadCount", `${state.audit.length} loaded`);
  host.innerHTML = rows.length
    ? `<div class="table-wrap"><table class="table table--compact">
        <thead><tr><th>Time</th><th>Action</th><th>Actor</th><th>Request</th><th>Reason / detail</th></tr></thead>
        <tbody>${rows.map((row) => auditRow(row)).join("")}</tbody></table></div>`
    : `<div class="table-empty">No audit entries match.</div>`;
  bindAuditRequestLinks(host);
}

/* ------------------------------------------------------------------ */
/* Settings                                                           */
/* ------------------------------------------------------------------ */

function wireSettings() {
  qs("#saveSettings")?.addEventListener("click", saveApprovalRules);
  qs("#saveThresholds")?.addEventListener("click", saveThresholds);
  qs("#saveReserve")?.addEventListener("click", saveCentralReserve);
  qs("#seedDemoButton")?.addEventListener("click", seedDemo);
}

function renderSettings() {
  const settings = state.settings;
  if (!settings) return;
  qs("#setAutoApprove").checked = Boolean(settings.autoApproveEnabled);
  qs("#setMaxRisk").value = settings.autoApproveMaxRisk ?? 20;
  qs("#setMinDesc").value = settings.autoApproveMinDescriptionLength ?? 20;
  qs("#setRequireContact").checked = Boolean(settings.autoApproveRequireContact);
  qs("#setBlockDuplicates").checked = settings.duplicateBlockAutoApprove !== false;
  qsa("#setSeverities input").forEach((input) => {
    input.checked = (settings.autoApproveSeverities || []).includes(input.value);
  });
  qs("#setDupWindow").value = settings.duplicateWindowHours ?? 72;
  qs("#setDupThreshold").value = settings.duplicateThreshold ?? 60;
  qs("#setMedium").value = settings.mediumRiskThreshold ?? 25;
  qs("#setHigh").value = settings.highRiskThreshold ?? 55;
  qs("#setRateLimit").value = settings.submissionRateLimit ?? 6;
  qs("#setRateWindow").value = settings.submissionRateWindowMinutes ?? 10;
  renderRoutingInfo();
  renderReserveForm();
}

function renderRoutingInfo() {
  const host = qs("#routingInfo");
  if (!host) return;
  const routing = state.routing || {};
  host.innerHTML = `<div class="detail-grid">
    <div class="detail-item"><span>Road routing</span><strong>OSRM</strong><div class="tiny muted">${esc(routing.routingUrl || "server default")}</div></div>
    <div class="detail-item"><span>Place search</span><strong>Nominatim</strong><div class="tiny muted">${esc(routing.geocodingUrl || "server default")}</div></div>
    <div class="detail-item"><span>Timeout</span><strong>${esc(state.routing?.timeoutSeconds ?? "—")} s</strong></div>
    <div class="detail-item"><span>Offline mode</span><strong>${routing.offline ? "On (estimates only)" : "Off"}</strong></div>
  </div>
  <div class="notice notice--info mt-16">${icon("info", 16)}<span>Routing and geocoding calls are proxied by the server, so no third-party key or origin is exposed in this page. When OSRM is unreachable, distances are labelled as estimates and no route line is drawn.</span></div>`;
}

function renderReserveForm() {
  const host = qs("#reserveForm");
  if (!host) return;
  host.innerHTML = RESOURCE_ORDER.map((category) => {
    const value = Number(state.inventory[category] || 0);
    return `<div class="resource-row">
      <label class="resource-row__label" for="reserve_${category}">${esc(resourceLabel(category))}</label>
      <input class="input" id="reserve_${category}" data-reserve="${category}" type="number" min="0" step="1" value="${value}">
    </div>`;
  }).join("");
  if (state.role !== "admin") {
    qsa("[data-reserve]", host).forEach((input) => {
      input.disabled = true;
    });
  }
}

async function saveApprovalRules() {
  const status = qs("#settingsStatus");
  const payload = {
    autoApproveEnabled: qs("#setAutoApprove").checked,
    autoApproveMaxRisk: Number(qs("#setMaxRisk").value),
    autoApproveSeverities: qsa("#setSeverities input:checked").map((input) => input.value),
    autoApproveMinDescriptionLength: Number(qs("#setMinDesc").value),
    autoApproveRequireContact: qs("#setRequireContact").checked,
    duplicateBlockAutoApprove: qs("#setBlockDuplicates").checked,
  };
  status.textContent = "Saving…";
  try {
    const result = await api.updateSettings(payload);
    state.settings = result.settings;
    status.textContent = "Saved";
    toast("Approval rules saved", payload.autoApproveEnabled ? "Auto-approval is enabled for qualifying low-risk requests." : "Auto-approval remains disabled.", "ok");
    await loadAll({ quiet: true });
  } catch (error) {
    status.textContent = "";
    toast("Could not save rules", error.message, "error");
  }
}

async function saveThresholds() {
  const status = qs("#thresholdsStatus");
  const medium = Number(qs("#setMedium").value);
  const high = Number(qs("#setHigh").value);
  if (medium >= high) {
    toast("Check thresholds", "The medium-risk threshold must be lower than the high-risk threshold.", "error");
    return;
  }
  const maxAutoRisk = Number(qs("#setMaxRisk").value);
  if (maxAutoRisk >= medium) {
    toast(
      "Check thresholds",
      "The auto-approval risk ceiling must stay below the medium-risk threshold, so medium-risk reports always get human review.",
      "error",
    );
    return;
  }
  const payload = {
    duplicateWindowHours: Number(qs("#setDupWindow").value),
    duplicateThreshold: Number(qs("#setDupThreshold").value),
    mediumRiskThreshold: medium,
    highRiskThreshold: high,
    submissionRateLimit: Number(qs("#setRateLimit").value),
    submissionRateWindowMinutes: Number(qs("#setRateWindow").value),
  };
  status.textContent = "Saving…";
  try {
    const result = await api.updateSettings(payload);
    state.settings = result.settings;
    status.textContent = "Saved";
    toast("Thresholds saved", "New reports will use these values.", "ok");
  } catch (error) {
    status.textContent = "";
    toast("Could not save thresholds", error.message, "error");
  }
}

async function saveCentralReserve() {
  const status = qs("#reserveStatus");
  const quantities = {};
  qsa("[data-reserve]").forEach((input) => {
    quantities[input.dataset.reserve] = Number(input.value || 0);
  });
  status.textContent = "Saving…";
  try {
    const result = await api.updateInventory({ quantities });
    state.inventory = result.inventory;
    status.textContent = "Saved";
    toast("Central reserve updated", "Stock levels saved.", "ok");
    await loadAll({ quiet: true });
  } catch (error) {
    status.textContent = "";
    toast("Could not update reserve", error.message, "error");
  }
}

function seedDemo() {
  confirmAction({
    title: "Insert demo incidents?",
    intro: "Adds nine realistic sample reports to the current database, including a duplicate pair and a high-risk report. Safe to run once.",
    confirmLabel: "Insert demo data",
    run: async () => {
      const result = await api.seedDemo();
      toast("Demo data", result.message || "Seeded.", "ok");
      await loadAll({ quiet: true });
    },
  });
}

/* ------------------------------------------------------------------ */
/* Dialogs / toasts                                                   */
/* ------------------------------------------------------------------ */

function wireDialogs() {
  qs("#dialogCancel")?.addEventListener("click", () => qs("#actionDialog").close());
  qs("#dialogConfirm")?.addEventListener("click", async () => {
    if (typeof dialogHandler !== "function") return;
    const dialog = qs("#actionDialog");
    const errorNode = qs("#dialogError");
    const confirm = qs("#dialogConfirm");
    errorNode.textContent = "";
    const values = collectDialogValues();
    const required = qsa("[data-dialog-required]", qs("#dialogBody"));
    for (const node of required) {
      if (!String(values[node.name] || "").trim()) {
        errorNode.textContent = "This field is required.";
        node.focus();
        return;
      }
    }
    const original = confirm.textContent;
    confirm.disabled = true;
    confirm.innerHTML = `<span class="spinner"></span> Working…`;
    try {
      await dialogHandler(values);
      dialog.close();
    } catch (error) {
      errorNode.textContent = error.message || "The action failed.";
    } finally {
      confirm.disabled = false;
      confirm.textContent = original;
    }
  });

  qs("#actionDialog")?.addEventListener("close", () => {
    dialogHandler = null;
    qs("#dialogBody").innerHTML = "";
    qs("#dialogError").textContent = "";
  });
}

function openDialog({ title, intro, fields = [], confirmLabel = "Confirm", tone = "primary", onConfirm }) {
  const dialog = qs("#actionDialog");
  qs("#dialogTitle").textContent = title;
  qs("#dialogIntro").textContent = intro || "";
  const body = qs("#dialogBody");
  body.innerHTML = fields
    .map((field) => {
      const required = field.required ? "data-dialog-required" : "";
      const label = field.label ? `<label for="dialog_${field.name}">${esc(field.label)}</label>` : "";
      if (field.type === "textarea") {
        return `<div class="field">${label}
          <textarea class="textarea" id="dialog_${field.name}" name="${esc(field.name)}" rows="4" ${required} placeholder="${esc(field.placeholder || "")}">${esc(field.value || "")}</textarea>
        </div>`;
      }
      return `<div class="field">${label}
        <input class="input" id="dialog_${field.name}" name="${esc(field.name)}" type="${esc(field.type || "text")}"
          value="${esc(field.value || "")}" ${field.min !== undefined ? `min="${field.min}"` : ""}
          ${field.max !== undefined ? `max="${field.max}"` : ""} ${required} placeholder="${esc(field.placeholder || "")}">
      </div>`;
    })
    .join("");
  const confirm = qs("#dialogConfirm");
  confirm.className = `btn btn--${tone === "danger" ? "danger" : tone === "ok" ? "ok" : "primary"} btn--sm`;
  confirm.textContent = confirmLabel;
  qs("#dialogError").textContent = "";
  dialogHandler = onConfirm;
  dialog.showModal();
  setTimeout(() => body.querySelector("textarea, input")?.focus(), 40);
}

function confirmAction({ title, intro, confirmLabel = "Confirm", run }) {
  openDialog({
    title,
    intro,
    fields: [],
    confirmLabel,
    onConfirm: async () => {
      await run();
    },
  });
}

function collectDialogValues() {
  const values = {};
  qsa("[name]", qs("#dialogBody")).forEach((node) => {
    values[node.name] = node.value;
  });
  return values;
}

function toast(title, message, tone = "info") {
  const stack = qs("#toastStack");
  if (!stack) return;
  const node = document.createElement("div");
  node.className = `toast toast--${tone}`;
  node.setAttribute("role", tone === "error" ? "alert" : "status");
  node.innerHTML = `${icon(tone === "error" ? "alert" : tone === "ok" ? "check-circle" : "info", 17)}
    <div><strong>${esc(title)}</strong>${message ? `<span>${esc(message)}</span>` : ""}</div>`;
  stack.appendChild(node);
  setTimeout(() => node.remove(), 6000);
}

/* attach the overview map lazily once a render is available */
const overviewObserver = new MutationObserver(() => {
  if (!qs("#viewOverview").hidden) initOverviewMap();
});
document.addEventListener("DOMContentLoaded", () => {
  const target = qs("#viewOverview");
  if (target) overviewObserver.observe(target, { attributes: true, attributeFilter: ["hidden"] });
});
