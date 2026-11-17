import {
  $, $$, api, clearSession, debounce, escapeHtml, fmtDate, resourceSummary,
  setSession, statusBadge, toast,
} from "./api.js";
import { MapView } from "./map.js";

const RESOURCES = ["Food", "Water", "Medicine", "RescueTeam", "MedicalTeam", "Shelter", "Other"];
const RESOURCE_LABELS = {
  Food: "Food", Water: "Water", Medicine: "Medicine", RescueTeam: "Rescue team",
  MedicalTeam: "Medical team", Shelter: "Shelter", Other: "Other",
};
const state = { requests: [], centres: [], settings: null, map: null, current: null };
let filterTimer;

function showLogin(message = "") {
  $("#adminApp").hidden = true;
  $("#adminLogin").hidden = false;
  const error = $("#adminLoginError");
  error.textContent = message;
  error.hidden = !message;
  checkHealth();
  $("#adminPassword").focus();
}

async function checkHealth() {
  try {
    const health = await api("/api/health");
    $("#loginHint").textContent = health.passwordConfigured
      ? "Admin password is configured. Enter it above."
      : "No admin password is configured. Run: python3 backend/app.py --set-password";
  } catch {
    $("#loginHint").textContent = "Server is not reachable right now.";
  }
}

async function init() {
  setupEvents();
  try {
    const session = await api("/api/admin/session");
    setSession(session);
    showApp();
  } catch (error) {
    showLogin(error.status === 401 ? "" : error.message);
  }
}

function showApp() {
  $("#adminLogin").hidden = true;
  $("#adminApp").hidden = false;
  loadAll();
}

function setupEvents() {
  $("#adminLoginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = $("#adminLoginError");
    error.hidden = true;
    clearSession();
    try {
      const data = await api("/api/admin/login", {
        method: "POST", body: { password: $("#adminPassword").value },
      });
      setSession(data);
      showApp();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });
  $("#adminLogout").addEventListener("click", async () => {
    try { await api("/api/admin/logout", { method: "POST" }); } catch { /* already expired */ }
    clearSession();
    showLogin();
  });
  $$("[data-tab]").forEach((button) => button.addEventListener("click", () => showTab(button.dataset.tab)));
  $$("[data-goto]").forEach((button) => button.addEventListener("click", () => showTab(button.dataset.goto)));
  $("#refreshButton").addEventListener("click", loadAll);
  $("#applyFilters").addEventListener("click", renderRequests);
  $("#requestSearch").addEventListener("input", debounce(renderRequests, 250));
  $("#statusFilter").addEventListener("change", renderRequests);
  $("#queueFilter").addEventListener("change", renderRequests);
  $("#addCentre").addEventListener("click", () => openCentreDialog(null));
  $("[data-close-centre]").addEventListener("click", () => $("#centreDialog").close());
  $("#centreForm").addEventListener("submit", saveCentre);
  $("#approvalForm").addEventListener("submit", saveApproval);
  $("#duplicateForm").addEventListener("submit", saveDuplicates);
  $("#seedDemo").addEventListener("click", seedDemo);
  $("#drawerOverlay").addEventListener("click", closeDrawer);
}

const TAB_TEXT = {
  overview: ["Overview", "Live request and resource summary"],
  requests: ["Requests", "Review, approve, reject and allocate"],
  resources: ["Help centres", "Manage centres, availability and stock"],
  map: ["Map", "Disaster reports and help-centre locations"],
  settings: ["Settings", "Verification and duplicate-detection rules"],
};

function showTab(name) {
  $$(".panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  $$("[data-tab]").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
  const [title, subtitle] = TAB_TEXT[name] || TAB_TEXT.overview;
  $("#pageTitle").textContent = title;
  $("#pageSub").textContent = subtitle;
  if (name === "map") ensureMap();
  if (name === "map" && state.map) {
    setTimeout(() => {
      state.map.refresh();
      state.map.fitAll();
    }, 80);
  }
}

async function loadAll() {
  try {
    const [stats, requestData, centreData, settingsData] = await Promise.all([
      api("/api/admin/stats"),
      api("/api/admin/requests"),
      api("/api/admin/centres"),
      api("/api/admin/settings"),
    ]);
    state.requests = requestData.requests || [];
    state.centres = centreData.centres || [];
    state.settings = settingsData.settings;
    renderStats(stats);
    renderRequests();
    renderCentres();
    renderSettings(settingsData);
    renderMap();
  } catch (error) {
    if (error.status === 401 || error.status === 403) showLogin("Your session expired. Sign in again.");
    else toast(`Could not load dashboard: ${error.message}`, "error");
  }
}

function riskBadge(request) {
  const level = request.riskLevel || "low";
  return `<span class="risk-${escapeHtml(level)}">${escapeHtml(level)} · ${Number(request.riskScore || 0)}</span>`;
}

function renderStats(stats) {
  $("#ovTotal").textContent = stats.total;
  $("#ovPending").textContent = stats.pending;
  $("#ovDuplicates").textContent = stats.duplicates;
  $("#ovActive").textContent = stats.active;
  $("#ovResolved").textContent = stats.resolved;
  $("#ovCentres").textContent = stats.centres;
  $("#ovStock").textContent = Number(stats.stockUnits).toLocaleString("en-IN");
  $("#ovAllocations").textContent = stats.allocations;
  const pending = state.requests.filter((item) => item.status === "pending");
  const rows = [
    ["Duplicate review", pending.filter((item) => item.reviewQueue === "duplicate_review").length, "duplicate_review"],
    ["High risk", pending.filter((item) => item.reviewQueue === "high_risk").length, "high_risk"],
    ["Manual review", pending.filter((item) => item.reviewQueue === "manual_review").length, "manual_review"],
  ];
  $("#queueSummary").innerHTML = rows.map(([label, count, queue]) => `
    <div class="list-item"><div><h3>${label}</h3><p>${count} request(s) waiting</p></div>
      <button class="btn btn-outline btn-sm" type="button" data-queue-jump="${queue}">Open</button></div>`).join("");
  $$("[data-queue-jump]").forEach((button) => button.addEventListener("click", () => {
    $("#statusFilter").value = "pending";
    $("#queueFilter").value = button.dataset.queueJump;
    showTab("requests");
    renderRequests();
  }));
  renderOverviewRequests();
}

function renderOverviewRequests() {
  const rows = state.requests.slice(0, 5).map((item) => `
    <tr><td><span class="row-link" data-request="${escapeHtml(item.id)}">${escapeHtml(item.id)}</span></td>
      <td>${escapeHtml(item.locationName)}</td>
      <td>${statusBadge(item.status, item.statusLabel)}</td>
      <td>${riskBadge(item)}</td></tr>`).join("");
  $("#overviewRequests").innerHTML = rows || '<tr><td colspan="4" class="empty">No requests yet. Add sample data from Settings.</td></tr>';
  bindRequestRows($("#overviewRequests"));
}

function filteredRequests() {
  const search = $("#requestSearch").value.trim().toLowerCase();
  const status = $("#statusFilter").value;
  const queue = $("#queueFilter").value;
  return state.requests.filter((item) => {
    if (status && item.status !== status) return false;
    if (queue && item.reviewQueue !== queue) return false;
    if (!search) return true;
    return [item.id, item.locationName, item.description, item.disasterType]
      .some((value) => String(value || "").toLowerCase().includes(search));
  });
}

function renderRequests() {
  const items = filteredRequests();
  $("#requestRows").innerHTML = items.length ? items.map((item) => `
    <tr><td><span class="row-link" data-request="${escapeHtml(item.id)}">${escapeHtml(item.id)}</span>
        ${item.possibleDuplicate ? '<span class="badge badge-orange">duplicate?</span>' : ""}</td>
      <td><strong>${escapeHtml(item.typeLabel)}</strong><br><span class="hint">${escapeHtml(item.locationName)}</span></td>
      <td>${escapeHtml(item.people)}</td>
      <td>${statusBadge(item.status, item.statusLabel)}</td>
      <td>${escapeHtml(item.reviewQueueLabel || "—")}</td>
      <td>${riskBadge(item)}</td>
      <td>${escapeHtml(fmtDate(item.createdAt, true))}</td>
      <td><button class="btn btn-outline btn-sm" type="button" data-request="${escapeHtml(item.id)}">Open</button></td></tr>`).join("")
    : '<tr><td colspan="8" class="empty">No requests match these filters.</td></tr>';
  bindRequestRows($("#requestRows"));
}

function bindRequestRows(root) {
  $$("[data-request]", root).forEach((element) => element.addEventListener("click", () => openRequest(element.dataset.request)));
}

async function openRequest(requestId) {
  try {
    const data = await api(`/api/admin/requests/${encodeURIComponent(requestId)}`);
    state.current = data.request;
    renderDrawer(data.request);
    $("#drawerOverlay").hidden = false;
    $("#requestDrawer").hidden = false;
  } catch (error) {
    toast(`Could not open request: ${error.message}`, "error");
  }
}

function closeDrawer() {
  $("#drawerOverlay").hidden = true;
  $("#requestDrawer").hidden = true;
  state.current = null;
}

function renderDrawer(request) {
  const duplicates = (request.duplicateMatches || []).filter((item) => item.isPossibleDuplicate);
  const history = (request.history || []).map((item) => `
    <div class="timeline-item"><span class="timeline-dot"></span><div><strong>${escapeHtml(item.label)}</strong>
      <p>${escapeHtml(fmtDate(item.createdAt, true))}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</p></div></div>`).join("");
  const evidence = (request.evidence || []).map((item) => `
    <button class="btn btn-outline btn-sm" type="button" data-evidence="${escapeHtml(item.id)}">${escapeHtml(item.name)}</button>`).join(" ");
  const allocation = request.allocation ? `
    <section class="card">
      <div class="between"><div><div class="section-title">Current allocation</div><h3>${escapeHtml(request.allocation.centreName || request.allocation.centreId)}</h3>
        <p class="hint">${escapeHtml(request.allocation.status)} · ${Number(request.allocation.distanceKm || 0).toFixed(1)} km · ${escapeHtml(request.allocation.distanceSource)}</p></div>
        <span class="badge badge-blue">${escapeHtml(request.allocation.status)}</span></div>
      <p class="small" style="margin-top:8px">${escapeHtml(resourceSummary(request.allocation.items))}</p>
      <div class="action-row" style="margin-top:10px">
        ${request.allocation.status === "assigned" ? `<button class="btn btn-primary btn-sm" type="button" data-allocation="${escapeHtml(request.allocation.id)}" data-allocation-action="dispatched">Dispatch</button>` : ""}
        ${request.allocation.status === "dispatched" ? `<button class="btn btn-success btn-sm" type="button" data-allocation="${escapeHtml(request.allocation.id)}" data-allocation-action="delivered">Mark delivered</button>` : ""}
        ${request.allocation.status !== "delivered" ? `<button class="btn btn-outline btn-sm" type="button" data-allocation="${escapeHtml(request.allocation.id)}" data-allocation-action="cancelled">Cancel allocation</button>` : ""}
      </div>
    </section>` : "";

  $("#drawerContent").innerHTML = `
    <div class="drawer-head"><div><span class="hint mono">${escapeHtml(request.id)}</span><h2>${escapeHtml(request.typeLabel)} at ${escapeHtml(request.locationName)}</h2>
      <div class="chips">${statusBadge(request.status, request.statusLabel)} ${riskBadge(request)}
        ${request.autoApproved ? '<span class="badge badge-blue">Auto-approved</span>' : ""}
        ${request.possibleDuplicate ? '<span class="badge badge-orange">Possible duplicate</span>' : ""}
        ${request.isDemo ? '<span class="badge badge-neutral">Sample data</span>' : ""}</div></div>
      <button class="drawer-close" type="button" id="drawerClose" aria-label="Close"><svg class="icon"><use href="#i-x"/></svg></button></div>
    <div class="drawer-body">
      <section class="detail-grid">
        <div><dt>Disaster</dt><dd>${escapeHtml(request.typeLabel)}</dd></div>
        <div><dt>Severity</dt><dd>${escapeHtml(request.severity)}</dd></div>
        <div><dt>People affected</dt><dd>${escapeHtml(request.people)}</dd></div>
        <div><dt>Submitted</dt><dd>${escapeHtml(fmtDate(request.createdAt, true))}</dd></div>
        <div><dt>Contact</dt><dd>${escapeHtml(request.contactName || "Not given")}</dd></div>
        <div><dt>Phone / email</dt><dd>${escapeHtml(request.contactPhone || request.contactEmail || "Not given")}</dd></div>
      </section>
      <section><div class="section-title">Description</div><p class="small">${escapeHtml(request.description)}</p></section>
      <section><div class="section-title">Requested resources</div><p class="small">${escapeHtml(resourceSummary(request.resources))}</p></section>
      ${duplicates.length ? `<section><div class="section-title">Duplicate warning</div>
        ${duplicates.map((match) => `<div class="dup-card"><strong>${escapeHtml(match.id)} · score ${escapeHtml(match.score)}</strong>
          <div>${escapeHtml(match.reasons.join(" · "))}</div><p>Never rejected automatically. Compare both reports before deciding.</p></div>`).join("")}
      </section>` : ""}
      <section><div class="section-title">Risk score ${Number(request.riskScore || 0)} / 100</div>
        ${(request.riskReasons || []).length ? request.riskReasons.map((reason) => `<div class="factor"><span>${escapeHtml(reason)}</span></div>`).join("") : '<p class="hint">No risk flags were raised.</p>'}
      </section>
      ${evidence ? `<section><div class="section-title">Evidence</div>${evidence}</section>` : ""}
      ${allocation}
      <section><div class="section-title">Decision and allocation</div>
        <textarea class="input" id="actionNote" rows="2" placeholder="Reason or message (required for reject / more info)"></textarea>
        <div class="action-row" style="margin-top:8px">
          ${request.status === "pending" ? '<button class="btn btn-success btn-sm" type="button" data-action="approve">Approve</button><button class="btn btn-warning btn-sm" type="button" data-action="request_info">Ask for info</button><button class="btn btn-danger btn-sm" type="button" data-action="reject">Reject</button>' : ""}
          ${["approved", "assigned"].includes(request.status) ? '<button class="btn btn-primary btn-sm" type="button" data-action="start">Start response</button>' : ""}
          ${["approved", "assigned", "in_progress"].includes(request.status) ? '<button class="btn btn-outline btn-sm" type="button" data-action="resolve">Resolve</button>' : ""}
          ${["approved", "assigned", "in_progress"].includes(request.status) && !request.allocation ? '<button class="btn btn-secondary btn-sm" type="button" id="findCentres">Recommend centres</button>' : ""}
        </div>
        <div id="recommendationArea" class="stack" style="margin-top:12px"></div>
      </section>
      <section><div class="section-title">History</div><div class="timeline">${history || '<p class="hint">No history.</p>'}</div></section>
    </div>`;

  $("#drawerClose").addEventListener("click", closeDrawer);
  $$("[data-action]", $("#drawerContent")).forEach((button) => button.addEventListener("click", () => requestAction(button.dataset.action)));
  $$("[data-evidence]", $("#drawerContent")).forEach((button) => button.addEventListener("click", () => openEvidence(button.dataset.evidence)));
  $$("[data-allocation]", $("#drawerContent")).forEach((button) => button.addEventListener("click", () => {
    updateAllocation(button.dataset.allocation, button.dataset.allocationAction);
  }));
  const findButton = $("#findCentres");
  if (findButton) findButton.addEventListener("click", loadRecommendations);
}

async function requestAction(action) {
  if (!state.current) return;
  const note = $("#actionNote").value.trim();
  if (["reject", "request_info"].includes(action) && !note) {
    toast("Write a reason or message first.", "error");
    $("#actionNote").focus();
    return;
  }
  try {
    const data = await api(`/api/admin/requests/${encodeURIComponent(state.current.id)}/action`, {
      method: "POST", body: { action, reason: note },
    });
    toast(`Request ${action.replace("_", " ")} recorded.`, "success");
    await loadAll();
    renderDrawer(data.request);
    state.current = data.request;
  } catch (error) { toast(error.message, "error"); }
}

async function updateAllocation(allocationId, action) {
  if (action === "cancelled" && !window.confirm("Cancel this allocation and return the stock to the centre?")) return;
  try {
    const data = await api(`/api/admin/allocations/${encodeURIComponent(allocationId)}`, {
      method: "PATCH", body: { action },
    });
    toast(`Allocation ${action}.`, "success");
    await loadAll();
    state.current = data.request;
    renderDrawer(data.request);
  } catch (error) { toast(error.message, "error"); }
}

async function loadRecommendations() {
  if (!state.current) return;
  const host = $("#recommendationArea");
  host.innerHTML = '<p class="hint">Comparing centres…</p>';
  try {
    const data = await api(`/api/admin/requests/${encodeURIComponent(state.current.id)}/recommendations`);
    if (!data.candidates.length) { host.innerHTML = '<p class="hint">No open centre has stock for this request.</p>'; return; }
    host.innerHTML = `<p class="hint">${escapeHtml(data.note)}</p>` + data.candidates.map((candidate) => `
      <article class="card" style="box-shadow:none">
        <div class="between"><div><h3>${escapeHtml(candidate.name)}</h3><p class="hint">${escapeHtml(candidate.address)}</p></div>
          <span class="badge badge-blue">${Number(candidate.score).toFixed(1)} pts</span></div>
        <div class="centre-meta"><span><strong>${Number(candidate.distanceKm).toFixed(1)} km</strong></span>
          <span>${candidate.durationMin == null ? "—" : `${candidate.durationMin} min`}</span>
          <span>${escapeHtml(candidate.distanceSource)}</span><span>${candidate.coveragePct}% coverage</span></div>
        <p class="small" style="margin-top:6px">${escapeHtml(resourceSummary(candidate.supplied))}</p>
        ${candidate.missing.length ? `<p class="hint">Short: ${escapeHtml(candidate.missing.join(", "))}</p>` : ""}
        <button class="btn btn-primary btn-sm" type="button" data-assign-centre="${escapeHtml(candidate.centreId)}">Assign these resources</button>
      </article>`).join("");
    $$("[data-assign-centre]", host).forEach((button) => button.addEventListener("click", () => {
      const candidate = data.candidates.find((item) => item.centreId === button.dataset.assignCentre);
      if (candidate) assignCandidate(candidate);
    }));
  } catch (error) { host.innerHTML = `<div class="notice notice-error">${escapeHtml(error.message)}</div>`; }
}

async function assignCandidate(candidate) {
  let override = "";
  if (candidate.missing.length) {
    override = window.prompt("This is a partial allocation. Enter a reason:") || "";
    if (!override.trim()) return;
  }
  try {
    const data = await api(`/api/admin/requests/${encodeURIComponent(state.current.id)}/allocations`, {
      method: "POST",
      body: {
        centreId: candidate.centreId, items: candidate.supplied,
        distance: { distanceKm: candidate.distanceKm, durationMin: candidate.durationMin,
          distanceSource: candidate.distanceSource },
        overrideReason: override,
      },
    });
    toast("Resources assigned and stock deducted.", "success");
    await loadAll();
    state.current = data.request;
    renderDrawer(data.request);
  } catch (error) { toast(error.message, "error"); }
}

async function openEvidence(evidenceId) {
  try {
    const token = sessionStorage.getItem("drras_token");
    const response = await fetch(`/api/admin/evidence/${encodeURIComponent(evidenceId)}`, {
      credentials: "same-origin", headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error("Could not open the file.");
    const blob = await response.blob();
    window.open(URL.createObjectURL(blob), "_blank", "noopener");
  } catch (error) { toast(error.message, "error"); }
}

function renderCentres() {
  $("#centreRows").innerHTML = state.centres.length ? state.centres.map((centre) => `
    <tr class="centre-row"><td><strong>${escapeHtml(centre.name)}</strong>${centre.isDemo ? ' <span class="badge badge-neutral">sample</span>' : ""}<br><span class="hint">${escapeHtml(centre.address)}</span></td>
      <td>${escapeHtml(centre.categoryLabel)}</td>
      <td><span class="badge ${centre.availability === "available" ? "badge-green" : centre.availability === "closed" ? "badge-red" : "badge-orange"}">${escapeHtml(centre.availability)}</span></td>
      <td class="centre-stock">${escapeHtml(resourceSummary(centre.stock)) || "—"}</td>
      <td>${escapeHtml(centre.phone || "—")}</td>
      <td><button class="btn btn-outline btn-sm" type="button" data-edit-centre="${escapeHtml(centre.id)}">Edit</button></td></tr>`).join("")
    : '<tr><td colspan="6" class="empty">No help centres.</td></tr>';
  $$("[data-edit-centre]").forEach((button) => button.addEventListener("click", () => {
    const centre = state.centres.find((item) => item.id === button.dataset.editCentre);
    openCentreDialog(centre);
  }));
}

function stockFields(values = {}) {
  $("#centreStockFields").innerHTML = RESOURCES.map((name) => `
    <div class="resource-row"><label>${RESOURCE_LABELS[name]}</label>
      <input type="number" min="0" max="1000000" step="1" data-stock="${name}" value="${Number(values[name] || 0)}"></div>`).join("");
}

function openCentreDialog(centre) {
  $("#centreError").hidden = true;
  $("#centreId").value = centre ? centre.id : "";
  $("#centreDialogTitle").textContent = centre ? "Edit help centre" : "Add help centre";
  $("#centreName").value = centre ? centre.name : "";
  $("#centreCategory").value = centre ? centre.category : "hospital";
  $("#centreLat").value = centre ? centre.latitude : "30.3165";
  $("#centreLon").value = centre ? centre.longitude : "78.0322";
  $("#centreAddress").value = centre ? centre.address : "";
  $("#centrePhone").value = centre ? centre.phone : "";
  $("#centreAvailability").value = centre ? centre.availability : "available";
  $("#centreNotes").value = centre ? centre.notes : "";
  stockFields(centre ? centre.stock : {});
  $("#centreDialog").showModal();
}

async function saveCentre(event) {
  event.preventDefault();
  const errorBox = $("#centreError");
  errorBox.hidden = true;
  const stock = {};
  $$("[data-stock]").forEach((input) => { stock[input.dataset.stock] = Number(input.value || 0); });
  const payload = {
    name: $("#centreName").value.trim(), category: $("#centreCategory").value,
    latitude: Number($("#centreLat").value), longitude: Number($("#centreLon").value),
    address: $("#centreAddress").value.trim(), phone: $("#centrePhone").value.trim(),
    availability: $("#centreAvailability").value, notes: $("#centreNotes").value.trim(), stock,
  };
  const centreId = $("#centreId").value;
  try {
    if (centreId) {
      await api(`/api/admin/centres/${encodeURIComponent(centreId)}`, { method: "PATCH", body: payload });
      toast("Centre updated.", "success");
    } else {
      await api("/api/admin/centres", { method: "POST", body: payload });
      toast("Centre added.", "success");
    }
    $("#centreDialog").close();
    await loadAll();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
}

function renderSettings(data) {
  const settings = data.settings;
  $("#autoEnabled").checked = Boolean(settings.autoApproveEnabled);
  $("#autoRisk").value = settings.autoApproveMaxRisk;
  $("#autoDescription").value = settings.autoApproveMinDescription;
  $("#autoContact").checked = Boolean(settings.autoApproveRequireContact);
  $$("#severityChoices input").forEach((input) => {
    input.checked = (settings.autoApproveSeverities || []).includes(input.value);
  });
  $("#duplicateThreshold").value = settings.duplicateThreshold;
  $("#duplicateWindow").value = settings.duplicateWindowHours;
  $("#routingInfo").textContent = `${data.routing.provider}: ${data.routing.note}`;
}

async function saveApproval(event) {
  event.preventDefault();
  const severities = $$("#severityChoices input:checked").map((input) => input.value);
  try {
    await api("/api/admin/settings", {
      method: "PATCH",
      body: {
        autoApproveEnabled: $("#autoEnabled").checked,
        autoApproveMaxRisk: Number($("#autoRisk").value),
        autoApproveMinDescription: Number($("#autoDescription").value),
        autoApproveRequireContact: $("#autoContact").checked,
        autoApproveSeverities: severities,
      },
    });
    toast("Approval rules saved.", "success");
    await loadAll();
  } catch (error) { toast(error.message, "error"); }
}

async function saveDuplicates(event) {
  event.preventDefault();
  try {
    await api("/api/admin/settings", {
      method: "PATCH",
      body: {
        duplicateThreshold: Number($("#duplicateThreshold").value),
        duplicateWindowHours: Number($("#duplicateWindow").value),
      },
    });
    toast("Duplicate rules saved.", "success");
    await loadAll();
  } catch (error) { toast(error.message, "error"); }
}

async function seedDemo() {
  if (!window.confirm("Insert or reset the four sample requests?")) return;
  try {
    const result = await api("/api/admin/seed-demo", { method: "POST" });
    toast(`${result.inserted} sample requests inserted.`, "success");
    await loadAll();
  } catch (error) { toast(error.message, "error"); }
}

function ensureMap() {
  if (!state.map) {
    state.map = new MapView("adminMap", { center: [30.3165, 78.0322], zoom: 10 });
    renderMap();
  }
  state.map.refresh();
}

function renderMap() {
  if (!state.map) return;
  state.map.setCentres(state.centres, {
    onClick: (centre) => toast(`${centre.name} · ${centre.availability}`),
  });
  state.map.setIncidents(state.requests, { onClick: (request) => openRequest(request.id) });
  state.map.fitAll();
}

init();
