import { DisasterManager } from "./disasterManager.js";
import { ResourceManager } from "./resourceManager.js";
import { HospitalManager } from "./hospitalManager.js";
import { ShelterManager } from "./shelterManager.js";
import { AllocationManager } from "./allocationManager.js";
import { AnalyticsManager } from "./analyticsManager.js";
import { RouteManager } from "./routeManager.js";
import { sortByDistance } from "./distanceCalculator.js";
import { seedDisasters, seedResources, seedHospitals, seedShelters } from "./seedData.js";
import { clearAll } from "./storage.js";
import {
  bannerText,
  listNotifications,
  markNotificationRead,
  submitRequest,
} from "./requestService.js";
import * as ui from "./ui.js";

// ---- Initialize managers ----
const disasterManager = new DisasterManager();
const resourceManager = new ResourceManager();
const hospitalManager = new HospitalManager();
const shelterManager = new ShelterManager();
const allocationManager = new AllocationManager(resourceManager, disasterManager);
const analyticsManager = new AnalyticsManager(disasterManager, resourceManager, allocationManager);
const routeManager = new RouteManager();

// ---- Seed sample data on first run ----
function seedIfEmpty() {
  if (!disasterManager.getAll().length) seedDisasters.forEach((d) => disasterManager.add(d));
  if (!resourceManager.getAll().length) seedResources.forEach((r) => resourceManager.add(r));
  if (!hospitalManager.getAll().length) seedHospitals.forEach((h) => hospitalManager.add(h));
  if (!shelterManager.getAll().length) seedShelters.forEach((s) => shelterManager.add(s));
}
seedIfEmpty();

// ---- Tab navigation ----
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.target).classList.remove("hidden");
    refreshAll();
    if (btn.dataset.target === "notifications") refreshUserNotifications();
  });
});

// ---- Build simulated road network from all known locations ----
function buildRouteNetwork() {
  routeManager.clear();
  disasterManager.getAll().forEach((d) => routeManager.addLocation(d.locationName, d.latitude, d.longitude));
  resourceManager.getAll().forEach((r) => routeManager.addLocation(r.locationName, r.latitude, r.longitude));
  hospitalManager.getAll().forEach((h) => routeManager.addLocation(h.name, h.latitude, h.longitude));
  shelterManager.getAll().forEach((s) => routeManager.addLocation(s.name, s.latitude, s.longitude));
  routeManager.buildSimulatedNetwork(5);
}

// ---- Refresh everything visible ----
function refreshAll() {
  ui.renderStats(analyticsManager.getStats());
  ui.renderDisasterList(disasterManager.getByPriorityOrder());
  ui.renderResourceTable(resourceManager.getAll());
  ui.renderHospitalTable(hospitalManager.getAll());
  ui.renderShelterTable(shelterManager.getAll());
  ui.renderAllocationTable(allocationManager.getHistory());

  ui.populateSelect(ui.el("hospitalDisasterSelect"), disasterManager.getActive(), (d) => `${d.id} - ${d.locationName}`);
  ui.populateSelect(ui.el("shelterDisasterSelect"), disasterManager.getActive(), (d) => `${d.id} - ${d.locationName}`);
  ui.populateSelect(ui.el("allocateDisasterSelect"), disasterManager.getActive(), (d) => `${d.id} - ${d.severity}`);

  buildRouteNetwork();
  ui.populateLocationSelect(ui.el("routeSource"), routeManager.listLocations());
  ui.populateLocationSelect(ui.el("routeDestination"), routeManager.listLocations());
}

// ================= PUBLIC REQUEST FORM =================
ui.el("disasterForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitButton = e.submitter || e.currentTarget.querySelector('button[type="submit"]');
  const originalLabel = submitButton.textContent;
  submitButton.disabled = true;
  submitButton.textContent = "Submitting…";

  try {
    const payload = {
      type: ui.el("dType").value,
      severity: ui.el("dSeverity").value,
      affectedPeople: Number(ui.el("dAffected").value),
      itemName: ui.el("dResourceItem").value.trim(),
      requestedQuantity: Number(ui.el("dRequestedQuantity").value),
      isCritical: ui.el("dSeverity").value === "CRITICAL",
      requiredResources: [...document.querySelectorAll("#disasterForm .checkbox-group input:checked")].map((c) => c.value),
      locationName: ui.el("dLocation").value.trim(),
      latitude: Number(ui.el("dLat").value),
      longitude: Number(ui.el("dLon").value),
    };
    // Same call either way: the service posts to /api when it can and to
    // browser storage when the site is hosted without a server.
    const result = await submitRequest(payload);
    const request = result.request;

    // Requests are centrally stored and reviewed before entering operations.
    const nearestHospitals = sortByDistance(hospitalManager.getAll(), request.latitude, request.longitude).slice(0, 3);
    const nearestShelters = sortByDistance(shelterManager.getAll(), request.latitude, request.longitude).slice(0, 3);
    const lines = [
      `Request ID       : ${request.id}`,
      `Review status    : PENDING`,
      `Resource request : ${request.requestedQuantity} ${request.itemName}`,
      `Stored in        : ${result.mode === "server" ? "the shared request database" : "this browser only (no server)"}`,
      `Location         : ${request.locationName}`,
      ``,
      `Nearest Hospitals:`,
      ...nearestHospitals.map((h, i) => `  ${i + 1}. ${h.item.id} (${h.item.name}) -> ${h.distance.toFixed(1)} km`),
      ``,
      `Nearest Shelters:`,
      ...nearestShelters.map((s, i) => `  ${i + 1}. ${s.item.id} (${s.item.name}) -> ${s.distance.toFixed(1)} km`),
    ];
    ui.showDistanceAnalysis(ui.el("disasterReportResult"), "REQUEST SUBMITTED — PENDING ADMIN REVIEW", lines);
    e.target.reset();
  } catch (err) {
    ui.showToast(err.message || "Could not reach the request service. Start the DRRAS admin server and try again.", true);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = originalLabel;
  }
});

// ================= RESOURCE FORM =================
ui.el("resourceForm").addEventListener("submit", (e) => {
  e.preventDefault();
  try {
    resourceManager.add({
      id: ui.el("rId").value.trim(),
      category: ui.el("rCategory").value,
      type: ui.el("rType").value.trim(),
      quantity: Number(ui.el("rQuantity").value),
      latitude: Number(ui.el("rLat").value),
      longitude: Number(ui.el("rLon").value),
      locationName: ui.el("rLocation").value.trim(),
      priority: Number(ui.el("rPriority").value),
      contact: ui.el("rContact").value.trim(),
    });
    e.target.reset();
    refreshAll();
    ui.showToast("Resource added.");
  } catch (err) { ui.showToast(err.message, true); }
});

document.querySelector("#resourceTable tbody").addEventListener("click", (e) => {
  if (!e.target.classList.contains("toggle-status")) return;
  const id = e.target.dataset.id;
  const current = e.target.dataset.status;
  const next = current === "AVAILABLE" ? "DISPATCHED" : "AVAILABLE";
  resourceManager.updateStatus(id, next);
  refreshAll();
});

ui.el("exportResourcesBtn").addEventListener("click", () => resourceManager.exportCSV());
ui.el("exportHospitalsBtn").addEventListener("click", () => hospitalManager.exportCSV());
ui.el("exportSheltersBtn").addEventListener("click", () => shelterManager.exportCSV());
ui.el("exportAllocationsBtn").addEventListener("click", () => allocationManager.exportCSV());

// ================= HOSPITAL FORM =================
ui.el("hospitalForm").addEventListener("submit", (e) => {
  e.preventDefault();
  try {
    hospitalManager.add({
      id: ui.el("hId").value.trim(), name: ui.el("hName").value.trim(),
      latitude: Number(ui.el("hLat").value), longitude: Number(ui.el("hLon").value),
      totalBeds: Number(ui.el("hTotal").value), availableBeds: Number(ui.el("hAvailable").value),
      emergencyCapacity: Number(ui.el("hEmergency").value),
    });
    e.target.reset();
    refreshAll();
  } catch (err) { ui.showToast(err.message, true); }
});

ui.el("findHospitalsBtn").addEventListener("click", () => {
  const disaster = disasterManager.getById(ui.el("hospitalDisasterSelect").value);
  if (!disaster) return ui.showToast("No active disaster selected.", true);
  const ranked = sortByDistance(hospitalManager.getAll(), disaster.latitude, disaster.longitude);
  const lines = [
    `Disaster Location : ${disaster.locationName}`,
    ...ranked.map((r, i) => `${i + 1}. ${r.item.id} (${r.item.name}) -> ${r.distance.toFixed(1)} km`),
  ];
  ui.showDistanceAnalysis(ui.el("nearestHospitalsResult"), "NEAREST HOSPITALS", lines);
});

// ================= SHELTER FORM =================
ui.el("shelterForm").addEventListener("submit", (e) => {
  e.preventDefault();
  try {
    shelterManager.add({
      id: ui.el("sId").value.trim(), name: ui.el("sName").value.trim(),
      latitude: Number(ui.el("sLat").value), longitude: Number(ui.el("sLon").value),
      capacity: Number(ui.el("sCapacity").value), occupied: Number(ui.el("sOccupied").value),
    });
    e.target.reset();
    refreshAll();
  } catch (err) { ui.showToast(err.message, true); }
});

ui.el("findSheltersBtn").addEventListener("click", () => {
  const disaster = disasterManager.getById(ui.el("shelterDisasterSelect").value);
  if (!disaster) return ui.showToast("No active disaster selected.", true);
  const ranked = sortByDistance(shelterManager.getAll(), disaster.latitude, disaster.longitude);
  const lines = [
    `Disaster Location : ${disaster.locationName}`,
    ...ranked.map((r, i) => `${i + 1}. ${r.item.id} (${r.item.name}) -> ${r.distance.toFixed(1)} km, Capacity left: ${r.item.availableCapacity}`),
  ];
  ui.showDistanceAnalysis(ui.el("nearestSheltersResult"), "NEAREST SHELTERS", lines);
});

// ================= ALLOCATION =================
ui.el("allocateBtn").addEventListener("click", () => {
  const disasterId = ui.el("allocateDisasterSelect").value;
  if (!disasterId) return ui.showToast("No active disaster selected.", true);
  try {
    const disaster = disasterManager.getById(disasterId);
    const results = allocationManager.allocateForDisaster(disasterId);

    const lines = [`Disaster  : ${disasterId}`, `Severity  : ${disaster.severity}`, ``];
    results.forEach((r) => {
      lines.push(`Available ${r.category}s:`);
      if (!r.candidates.length) { lines.push("  None available."); return; }
      r.candidates.forEach((c) => lines.push(`  ${c.item.id} -> ${c.distance.toFixed(1)} km`));
      lines.push(``);
      lines.push(`Selected Resource : ${r.selected.id}`);
      lines.push(`Distance          : ${r.distance.toFixed(1)} km`);
      lines.push(`Status            : DISPATCHED`);
      lines.push(``);
    });

    ui.showDistanceAnalysis(ui.el("allocationResult"), "RESOURCE ALLOCATION", lines);
    refreshAll();
  } catch (err) { ui.showToast(err.message, true); }
});

// ================= ROUTE FINDER =================
ui.el("findRouteBtn").addEventListener("click", () => {
  const source = ui.el("routeSource").value;
  const destination = ui.el("routeDestination").value;
  const result = routeManager.shortestPath(source, destination);

  if (!result.found) {
    ui.el("routeResult").innerHTML = `<div class="result-box">No path found between ${source} and ${destination}.</div>`;
    return;
  }
  const lines = [
    `Source               : ${source}`,
    `Destination          : ${destination}`,
    `Shortest Distance    : ${result.distance.toFixed(1)} km`,
    `Estimated Route      : ${result.path.join(" -> ")}`,
  ];
  ui.showDistanceAnalysis(ui.el("routeResult"), "SHORTEST ROUTE (SIMULATED NETWORK)", lines);
});

// ================= SEARCH =================
ui.el("searchDisasterBtn").addEventListener("click", () => {
  const d = disasterManager.getById(ui.el("searchDisasterId").value.trim());
  ui.el("searchResult").innerHTML = d
    ? `<div class="result-box">${JSON.stringify(d, null, 2)}</div>`
    : `<div class="result-box">No disaster found.</div>`;
});

ui.el("searchResourceBtn").addEventListener("click", () => {
  const r = resourceManager.getById(ui.el("searchResourceId").value.trim());
  ui.el("searchResult").innerHTML = r
    ? `<div class="result-box">${JSON.stringify(r, null, 2)}</div>`
    : `<div class="result-box">No resource found.</div>`;
});

ui.el("searchKeywordBtn").addEventListener("click", () => {
  const keyword = ui.el("searchKeyword").value.trim().toLowerCase();
  const matches = [
    ...disasterManager.getAll().filter((d) => d.locationName.toLowerCase().includes(keyword)),
    ...resourceManager.getAll().filter((r) => r.locationName.toLowerCase().includes(keyword)),
  ];
  ui.el("searchResult").innerHTML = matches.length
    ? `<div class="result-box">${matches.map((m) => JSON.stringify(m, null, 2)).join("\n\n")}</div>`
    : `<div class="result-box">No matches found.</div>`;
});

// ================= MISC =================
ui.el("refreshStatsBtn").addEventListener("click", refreshAll);

ui.el("resetDataBtn").addEventListener("click", () => {
  if (confirm("This will erase all stored data. Continue?")) {
    clearAll();
    location.reload();
  }
});

// Say out loud when there is no server, so "submitted" is never mistaken for
// "received by the control room".
bannerText().then((text) => {
  const banner = ui.el("serviceBanner");
  if (banner && text) {
    banner.textContent = text;
    banner.hidden = false;
  }
});

refreshAll();

// ================= STATUS MESSAGE HELPER =================
function getStatusDetails(status) {
  const s = String(status || "pending").toLowerCase();
  if (s === "accepted") {
    return {
      title: "Relief Request Accepted — Help is En Route!",
      message: "Your relief request has been APPROVED by the command center. Emergency resources have been allocated and relief units are being dispatched to your location.",
      advice: "Please stay in a safe, accessible area and keep your communication line open for response personnel.",
      badgeClass: "status-badge accepted",
      badgeText: "ACCEPTED",
    };
  } else if (s === "partially_approved") {
    return {
      title: "Critical Request Partially Approved",
      message: "Some resources are available now; the remaining amount may be provided if additional stock arrives.",
      advice: "Please check My Messages for the exact quantity allocated and keep your communication line open.",
      badgeClass: "status-badge partially-approved",
      badgeText: "PARTIALLY APPROVED",
    };
  } else if (s === "rejected") {
    return {
      title: "Request Reviewed and Closed",
      message: "Your relief request was reviewed and closed by coordinators. This typically happens if the zone is already covered by ongoing operations, duplicate requests were merged, or immediate assistance is redirected through primary emergency services.",
      advice: "If you are in immediate life-threatening danger, please contact local emergency authorities or call 112 directly.",
      badgeClass: "status-badge rejected",
      badgeText: "DECLINED / CLOSED",
    };
  } else {
    return {
      title: "Request Received — Awaiting Coordinator Review",
      message: "Your relief request has been received and logged into the emergency dispatch queue. Emergency coordinators are reviewing severity and matching available ambulances, teams, and supplies in your area.",
      advice: "Save your Request ID. Check back here periodically for updates on coordinator decisions and dispatch progress.",
      badgeClass: "status-badge pending",
      badgeText: "PENDING REVIEW",
    };
  }
}

function renderStatusCard(container, req, details) {
  const status = (req.status || "pending").toLowerCase();
  const reqRes = Array.isArray(req.requiredResources) && req.requiredResources.length
    ? req.requiredResources.join(", ")
    : "None";
  const submitted = req.submittedAt ? new Date(req.submittedAt).toLocaleString() : "Recently";
  const decided = req.decidedAt ? new Date(req.decidedAt).toLocaleString() : (status === "pending" ? "Awaiting decision" : "—");

  container.innerHTML = `
    <div class="status-alert ${status}">
      <div class="status-alert-header">
        <div>
          <h3>${details.title}</h3>
          <span style="font-family: monospace; font-size: 0.95rem; font-weight: bold; color: #374151;">
            ID: ${req.id}
          </span>
        </div>
        <span class="${details.badgeClass}">${details.badgeText}</span>
      </div>
      <p class="status-message-text"><strong>Status Update:</strong> ${details.message}</p>
      <p class="status-advice-text">👉 <strong>Next Steps:</strong> ${details.advice}</p>
      <div class="request-meta-grid">
        <div class="request-meta-item"><strong>Location</strong><span>${req.locationName || "—"}</span></div>
        <div class="request-meta-item"><strong>Disaster & Severity</strong><span>${req.type || "—"} (${req.severity || "—"})</span></div>
        <div class="request-meta-item"><strong>Resources Needed</strong><span>${reqRes}</span></div>
        <div class="request-meta-item"><strong>Affected People</strong><span>${Number(req.affectedPeople || 0).toLocaleString()}</span></div>
        <div class="request-meta-item"><strong>Submitted</strong><span>${submitted}</span></div>
        <div class="request-meta-item"><strong>Decision Time</strong><span>${decided}</span></div>
      </div>
    </div>
  `;
}

async function refreshUserNotifications() {
  const status = ui.el("notificationsStatus");
  const list = ui.el("notificationList");
  status.textContent = "Loading messages…";
  list.replaceChildren();
  try {
    const result = await listNotifications();
    const notifications = Array.isArray(result.notifications) ? result.notifications : [];
    status.textContent = notifications.length
      ? `${notifications.length} ${notifications.length === 1 ? "message" : "messages"}`
      : "No decision messages yet. Check back after your request is reviewed.";

    for (const notification of notifications) {
      const card = document.createElement("article");
      card.className = `notification-card ${notification.status === "UNREAD" ? "unread" : "read"}`;
      const header = document.createElement("div");
      header.className = "notification-heading";
      const requestLabel = document.createElement("strong");
      requestLabel.textContent = `Request ${notification.requestId}`;
      const state = document.createElement("span");
      state.textContent = notification.status === "READ" ? "Read" : "Unread";
      header.append(requestLabel, state);
      const message = document.createElement("p");
      message.textContent = notification.message;
      const time = document.createElement("small");
      const date = new Date(notification.createdAt);
      time.textContent = Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
      card.append(header, message, time);

      if (notification.status !== "READ") {
        const readButton = document.createElement("button");
        readButton.type = "button";
        readButton.className = "btn notification-read-button";
        readButton.textContent = "Mark as read";
        readButton.addEventListener("click", async () => {
          readButton.disabled = true;
          try {
            await markNotificationRead(notification.id);
            await refreshUserNotifications();
          } catch (error) {
            status.textContent = error.message || "Could not update this message.";
            readButton.disabled = false;
          }
        });
        card.append(readButton);
      }
      list.append(card);
    }
  } catch (error) {
    status.textContent = error.message || "Could not load messages.";
  }
}

ui.el("refreshNotificationsBtn").addEventListener("click", refreshUserNotifications);
