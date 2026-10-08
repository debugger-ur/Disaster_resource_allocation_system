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
  });
});

// ---- Build simulated road network from all known locations ----
function buildRouteNetwork() {
  routeManager.clear();
  disasterManager.getAll().forEach((d) => routeManager.addLocation(d.locationName, d.latitude, d.longitude));
  resourceManager.getAll().forEach((r) => routeManager.addLocation(r.locationName, r.latitude, r.longitude));
  hospitalManager.getAll().forEach((h) => routeManager.addLocation(h.name, h.latitude, h.longitude));
  shelterManager.getAll().forEach((s) => routeManager.addLocation(s.name, s.latitude, s.longitude));
  routeManager.buildSimulatedNetwork(3);
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

// ================= DISASTER FORM =================
ui.el("disasterForm").addEventListener("submit", (e) => {
  e.preventDefault();
  try {
    const required = [...document.querySelectorAll("#disasterForm .checkbox-group input:checked")].map((c) => c.value);
    const disaster = disasterManager.add({
      id: ui.el("dId").value.trim(),
      type: ui.el("dType").value,
      severity: ui.el("dSeverity").value,
      affectedPeople: Number(ui.el("dAffected").value),
      requiredResources: required,
      locationName: ui.el("dLocation").value.trim(),
      latitude: Number(ui.el("dLat").value),
      longitude: Number(ui.el("dLon").value),
    });

    // Automatic nearest hospital/shelter distance analysis
    const nearestHospitals = sortByDistance(hospitalManager.getAll(), disaster.latitude, disaster.longitude).slice(0, 3);
    const nearestShelters = sortByDistance(shelterManager.getAll(), disaster.latitude, disaster.longitude).slice(0, 3);

    const lines = [
      `Disaster Location : ${disaster.locationName}`,
      ``,
      `Nearest Hospitals:`,
      ...nearestHospitals.map((h, i) => `  ${i + 1}. ${h.item.id} (${h.item.name}) -> ${h.distance.toFixed(1)} km`),
      ``,
      `Nearest Shelters:`,
      ...nearestShelters.map((s, i) => `  ${i + 1}. ${s.item.id} (${s.item.name}) -> ${s.distance.toFixed(1)} km`),
    ];
    ui.showDistanceAnalysis(ui.el("disasterReportResult"), "DISASTER REPORTED — DISTANCE ANALYSIS", lines);

    e.target.reset();
    refreshAll();
  } catch (err) { ui.showToast(err.message, true); }
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

refreshAll();
