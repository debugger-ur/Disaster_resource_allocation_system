import {
  $, $$, api, debounce, escapeHtml, fmtDate, resourceSummary,
  statusBadge, timeAgo, toast,
} from "./api.js";
import { MapView } from "./map.js";

const RESOURCES = [
  ["Food", "Food packets"], ["Water", "Drinking water"], ["Medicine", "Medicines"],
  ["RescueTeam", "Rescue team"], ["MedicalTeam", "Medical team"],
  ["Shelter", "Shelter kits"], ["Other", "Other supplies"],
];
const state = {
  evidence: [], centres: [],
  origin: { latitude: 30.3165, longitude: 78.0322, label: "Dehradun (default map centre)" },
  homeMap: null, reportMap: null, nearbyMap: null, selectedCentre: null,
};

function showView(name) {
  const target = document.getElementById(`view-${name}`) ? name : "home";
  $$(".view").forEach((view) => { view.hidden = view.dataset.view !== target; });
  $$("[data-nav]").forEach((link) => link.classList.toggle("active", link.dataset.nav === target));
  if (window.location.hash !== `#${target}`) history.replaceState(null, "", `#${target}`);
  $("#siteNav").classList.remove("open");
  if (target === "report") ensureReportMap();
  if (target === "nearby") { ensureNearbyMap(); loadNearby(); }
  if (target === "home" && state.homeMap) state.homeMap.refresh();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setupNavigation() {
  $$("[data-nav]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    showView(link.dataset.nav);
  }));
  $("#navToggle").addEventListener("click", () => {
    const nav = $("#siteNav");
    nav.classList.toggle("open");
    $("#navToggle").setAttribute("aria-expanded", String(nav.classList.contains("open")));
  });
  window.addEventListener("hashchange", () => showView(location.hash.slice(1) || "home"));
}

async function loadOverview() {
  try {
    const [overview, centreData] = await Promise.all([api("/api/overview"), api("/api/centres")]);
    state.centres = centreData.centres || [];
    $("#statActive").textContent = overview.stats.activeIncidents;
    $("#statCentres").textContent = overview.stats.centres;
    $("#statPeople").textContent = Number(overview.stats.peopleReached).toLocaleString("en-IN");
    $("#statResolved").textContent = overview.stats.resolved;
    renderIncidents(overview.incidents || []);
    renderDispatches(overview.dispatches || []);
    if (state.homeMap) {
      state.homeMap.setCentres(state.centres);
      state.homeMap.setIncidents(overview.incidents || [], { onClick: chooseIncident });
      state.homeMap.fitAll();
    }
  } catch (error) {
    toast(`Could not load overview: ${error.message}`, "error");
  }
}

function renderIncidents(incidents) {
  const host = $("#incidentsList");
  if (!incidents.length) {
    host.innerHTML = '<div class="empty-box">No approved incidents yet. Sample requests can be added from the admin dashboard.</div>';
    return;
  }
  host.innerHTML = incidents.map((item) => `
    <article class="list-item">
      <div><h3>${escapeHtml(item.typeLabel)} · ${escapeHtml(item.locationName)}</h3>
        <p>${escapeHtml(item.people)} people · ${escapeHtml(resourceSummary(item.resources))}</p>
        <p>${escapeHtml(timeAgo(item.createdAt))} · ${escapeHtml(item.id)}</p></div>
      <button class="btn btn-outline btn-sm" type="button" data-incident="${escapeHtml(item.id)}">Find help</button>
    </article>`).join("");
  $$("[data-incident]", host).forEach((button) => button.addEventListener("click", () => {
    const incident = incidents.find((item) => item.id === button.dataset.incident);
    if (incident) chooseIncident(incident);
  }));
  if (state.homeMap) state.homeMap.setIncidents(incidents, { onClick: chooseIncident });
  $("#homeMapNote").textContent = `${incidents.length} active incident(s) · ${state.centres.length} sample centres`;
}

function renderDispatches(dispatches) {
  const host = $("#dispatchList");
  if (!dispatches.length) {
    host.innerHTML = '<div class="empty-box">No dispatches yet. Approved requests awaiting allocation appear in the admin dashboard.</div>';
    return;
  }
  host.innerHTML = dispatches.map((item) => `
    <div class="list-item"><div><h3>${escapeHtml(item.location)}</h3>
      <p>${escapeHtml(item.centre)} · ${escapeHtml(resourceSummary(item.items))}</p></div>
      <span class="badge ${item.status === "delivered" ? "badge-green" : "badge-blue"}">${escapeHtml(item.status)}</span></div>`).join("");
}

function chooseIncident(incident) {
  state.origin = {
    latitude: incident.latitude, longitude: incident.longitude,
    label: `${incident.typeLabel} at ${incident.locationName}`,
  };
  showView("nearby");
}

function ensureReportMap() {
  if (!state.reportMap) {
    state.reportMap = new MapView("reportMap", { center: [30.3165, 78.0322], zoom: 12 });
    state.reportMap.pick((point) => {
      $("#rLat").value = Number(point.lat).toFixed(6);
      $("#rLon").value = Number(point.lng).toFixed(6);
      $("#rLocationStatus").textContent = "Pin placed on the map. Add a recognisable location name.";
      if (!$("#rLocation").value.trim()) $("#rPlaceSearch").focus();
    });
    $("#reportMap").addEventListener("picker-move", (event) => {
      $("#rLat").value = Number(event.detail.latitude).toFixed(6);
      $("#rLon").value = Number(event.detail.longitude).toFixed(6);
    });
  }
  state.reportMap.refresh();
}

function setupReport() {
  $("#resourceRows").innerHTML = RESOURCES.map(([key, label]) => `
    <div class="resource-row"><label><input type="checkbox" data-resource="${key}"> ${label}</label>
      <input type="number" min="0" max="100000" step="1" data-qty="${key}" placeholder="Qty" aria-label="${label} quantity"></div>`).join("");
  $("#rDescription").addEventListener("input", () => {
    $("#descCount").textContent = `${$("#rDescription").value.length} / 2000`;
  });
  $("#rPlaceSearch").addEventListener("input", debounce(searchPlaces, 350));
  $("#rGeolocate").addEventListener("click", useGeolocation);
  $("#rFiles").addEventListener("change", (event) => uploadFiles(Array.from(event.target.files || [])));
  $("#reportForm").addEventListener("submit", submitReport);
}

async function searchPlaces() {
  const text = $("#rPlaceSearch").value.trim();
  const box = $("#placeSuggestions");
  if (text.length < 2) { box.hidden = true; return; }
  try {
    const data = await api(`/api/places?q=${encodeURIComponent(text)}`);
    if (!data.results.length) {
      box.innerHTML = '<div class="suggestion">No matching place. Click the map instead.</div>';
    } else {
      box.innerHTML = data.results.map((item, index) => `
        <button class="suggestion" type="button" data-place="${index}">${escapeHtml(item.name)}
          <span class="hint">${item.source === "nominatim" ? "OpenStreetMap" : "local"}</span></button>`).join("");
      $$("[data-place]", box).forEach((button) => button.addEventListener("click", () => {
        const item = data.results[Number(button.dataset.place)];
        applyPlace(item);
      }));
    }
    box.hidden = false;
  } catch { box.hidden = true; }
}

function applyPlace(item) {
  $("#rLat").value = Number(item.latitude).toFixed(6);
  $("#rLon").value = Number(item.longitude).toFixed(6);
  $("#rLocation").value = item.name.slice(0, 200);
  $("#rLocationStatus").textContent = `Selected: ${item.name}`;
  $("#placeSuggestions").hidden = true;
  ensureReportMap();
  if (state.reportMap) state.reportMap.setPicker(item.latitude, item.longitude);
}

function useGeolocation() {
  if (!navigator.geolocation) { toast("This browser does not support GPS location.", "error"); return; }
  const button = $("#rGeolocate");
  button.disabled = true;
  navigator.geolocation.getCurrentPosition((position) => {
    const { latitude, longitude } = position.coords;
    $("#rLat").value = latitude.toFixed(6);
    $("#rLon").value = longitude.toFixed(6);
    $("#rLocationStatus").textContent = "GPS location captured. Add a location name.";
    ensureReportMap();
    if (state.reportMap) state.reportMap.setPicker(latitude, longitude);
    button.disabled = false;
  }, (error) => {
    toast(`Could not read GPS: ${error.message}`, "error");
    button.disabled = false;
  }, { enableHighAccuracy: true, timeout: 10000 });
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function uploadFiles(files) {
  const allowed = ["image/jpeg", "image/png", "application/pdf"];
  for (const file of files) {
    if (state.evidence.length >= 3) { toast("Maximum three files.", "error"); break; }
    if (!allowed.includes(file.type)) { toast(`${file.name}: only JPEG, PNG or PDF.`, "error"); continue; }
    if (file.size > 5 * 1024 * 1024) { toast(`${file.name} is larger than 5 MB.`, "error"); continue; }
    try {
      const data = await readFile(file);
      const response = await api("/api/uploads", {
        method: "POST", body: { name: file.name, type: file.type, data },
      });
      state.evidence.push(response.evidence);
      renderEvidence();
    } catch (error) { toast(`Upload failed: ${error.message}`, "error"); }
  }
  $("#rFiles").value = "";
}

function renderEvidence() {
  $("#evidenceList").innerHTML = state.evidence.map((item) => `
    <span class="chip">${escapeHtml(item.name)} <button type="button" data-remove-evidence="${escapeHtml(item.id)}" aria-label="Remove">×</button></span>`).join("");
  $$("[data-remove-evidence]").forEach((button) => button.addEventListener("click", () => {
    state.evidence = state.evidence.filter((item) => item.id !== button.dataset.removeEvidence);
    renderEvidence();
  }));
}

async function submitReport(event) {
  event.preventDefault();
  const errorBox = $("#reportError");
  const button = $("#reportSubmit");
  errorBox.hidden = true;
  const latitude = Number($("#rLat").value);
  const longitude = Number($("#rLon").value);
  if (!$("#rLat").value || !$("#rLon").value || Number.isNaN(latitude) || Number.isNaN(longitude)) {
    errorBox.textContent = "Place the disaster location on the map, use GPS, or search for a place.";
    errorBox.hidden = false;
    ensureReportMap();
    return;
  }
  const resources = {};
  $$("[data-resource]").forEach((checkbox) => {
    if (!checkbox.checked) return;
    const quantity = Number($(`[data-qty="${checkbox.dataset.resource}"]`).value || 1);
    if (quantity > 0) resources[checkbox.dataset.resource] = Math.round(quantity);
  });
  if (!Object.keys(resources).length) {
    errorBox.textContent = "Tick at least one resource and enter a quantity.";
    errorBox.hidden = false;
    return;
  }
  const payload = {
    disasterType: $("#rType").value,
    severity: $('input[name="severity"]:checked').value,
    affectedPeople: Number($("#rAffected").value),
    description: $("#rDescription").value.trim(),
    locationName: $("#rLocation").value.trim(),
    latitude, longitude,
    contactName: $("#rContactName").value.trim(),
    contactPhone: $("#rContactPhone").value.trim(),
    contactEmail: $("#rContactEmail").value.trim(),
    resources,
    evidence: state.evidence.map((item) => item.id),
  };
  button.disabled = true;
  button.textContent = "Submitting…";
  try {
    const data = await api("/api/requests", { method: "POST", body: payload });
    state.evidence = [];
    renderEvidence();
    renderReceipt(data);
    toast("Report submitted. Keep the request ID.", "success");
    loadOverview();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
    button.innerHTML = 'Submit report <svg class="icon"><use href="#i-arrow"/></svg>';
  }
}

function renderReceipt(data) {
  const request = data.request;
  const host = $("#reportResult");
  host.hidden = false;
  host.innerHTML = `<div class="receipt"><p class="eyebrow">Report received</p>
    <h2>Keep this request ID</h2><div class="receipt-id">${escapeHtml(request.id)}</div>
    <p class="small">${escapeHtml(data.verification.summary)}</p>
    <p class="small" style="margin-top:6px">Status: ${statusBadge(request.status, request.statusLabel)}</p>
    <button class="btn btn-outline btn-sm" style="margin-top:10px" type="button" data-track-receipt="${escapeHtml(request.id)}">Track this report</button></div>`;
  $("[data-track-receipt]").addEventListener("click", () => {
    $("#trackId").value = request.id;
    showView("my");
    trackRequest();
  });
  host.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function ensureNearbyMap() {
  if (!state.nearbyMap) {
    state.nearbyMap = new MapView("nearbyMap", { center: [30.3165, 78.0322], zoom: 11 });
  }
  state.nearbyMap.refresh();
}

function setupNearby() {
  $("#nearbyFilters").addEventListener("change", loadNearby);
  $("#nearbyFilters").addEventListener("submit", (event) => event.preventDefault());
}

async function loadNearby() {
  ensureNearbyMap();
  const params = new URLSearchParams({
    lat: state.origin.latitude, lon: state.origin.longitude,
    radius: $("#nRadius").value || 50,
    category: $("#nCategory").value, availability: $("#nAvailability").value,
    resource: $("#nResource").value,
  });
  $("#nearbyOrigin").textContent = `Near ${state.origin.label}. Distances are road estimates or routed results, labelled on each card.`;
  try {
    const data = await api(`/api/nearby?${params}`);
    $("#nearbyCount").textContent = `${data.count} centre(s)`;
    state.centresForMap = data.centres || [];
    renderNearby(data.centres || []);
    if (state.nearbyMap) {
      state.nearbyMap.setOrigin(state.origin.latitude, state.origin.longitude);
      state.nearbyMap.setCentres(data.centres || [], { onClick: selectCentre, selectedId: state.selectedCentre });
      state.nearbyMap.fitAll();
    }
    const routed = (data.centres || []).filter((item) => item.distanceSource === "osrm").length;
    $("#routingNote").innerHTML = routed
      ? `<svg class="icon"><use href="#i-pin"/></svg> ${routed} of ${data.count} distances came from OSRM road routing.`
      : '<svg class="icon"><use href="#i-pin"/></svg> OSRM is unavailable, so distances are clearly labelled estimates. No route line is drawn.';
  } catch (error) {
    toast(`Could not load centres: ${error.message}`, "error");
  }
}

function renderNearby(centres) {
  const host = $("#nearbyList");
  if (!centres.length) {
    host.innerHTML = '<div class="empty-box">No centres match these filters.</div>';
    return;
  }
  host.innerHTML = centres.map((centre) => `
    <article class="centre-card" data-centre-card="${escapeHtml(centre.id)}">
      <div class="between"><h3>${escapeHtml(centre.name)}</h3>
        <span class="badge ${centre.availability === "available" ? "badge-green" : centre.availability === "closed" ? "badge-red" : "badge-orange"}">${escapeHtml(centre.availability)}</span></div>
      <p>${escapeHtml(centre.categoryLabel)} · ${escapeHtml(centre.address)}</p>
      <div class="centre-meta"><span><strong>${Number(centre.distanceKm).toFixed(1)} km</strong></span>
        <span>${centre.durationMin == null ? "—" : `${centre.durationMin} min`}</span>
        <span>${centre.distanceSource === "osrm" ? "road route" : "estimate"}</span></div>
      <div class="stock-line">${escapeHtml(resourceSummary(centre.stock)) || "No stock recorded"}</div>
      ${centre.phone ? `<div class="centre-meta"><span><svg class="icon"><use href="#i-phone"/></svg> ${escapeHtml(centre.phone)}</span></div>` : ""}
    </article>`).join("");
  $$("[data-centre-card]").forEach((card) => card.addEventListener("click", () => {
    const centre = centres.find((item) => item.id === card.dataset.centreCard);
    if (centre) selectCentre(centre);
  }));
}

async function selectCentre(centre) {
  state.selectedCentre = centre.id;
  $$("[data-centre-card]").forEach((card) => card.classList.toggle("selected", card.dataset.centreCard === centre.id));
  if (state.nearbyMap) {
    state.nearbyMap.setCentres(state.centresForMap || [], { onClick: selectCentre, selectedId: centre.id });
    state.nearbyMap.focus(centre.latitude, centre.longitude, 14);
  }
  try {
    const route = await api(`/api/route?fromLat=${state.origin.latitude}&fromLon=${state.origin.longitude}&toLat=${centre.latitude}&toLon=${centre.longitude}`);
    if (state.nearbyMap) state.nearbyMap.drawRoute(route.geometry);
    $("#routingNote").innerHTML = `<svg class="icon"><use href="#i-pin"/></svg> ${route.source === "osrm" ? "Live OSRM route" : "Estimated route"}: ${route.distanceKm} km · ${route.durationMin} min${route.source !== "osrm" ? " (routing unavailable)" : ""}.`;
  } catch (error) {
    toast(`Route unavailable: ${error.message}`, "error");
  }
}

function setupTrack() {
  $("#trackForm").addEventListener("submit", (event) => { event.preventDefault(); trackRequest(); });
}

async function trackRequest() {
  const id = $("#trackId").value.trim().toUpperCase();
  const host = $("#trackResult");
  if (!id) return;
  host.innerHTML = '<p class="muted small">Looking up request…</p>';
  try {
    const data = await api(`/api/requests/${encodeURIComponent(id)}`);
    renderTracked(data.request);
  } catch (error) {
    host.innerHTML = `<div class="notice notice-error">${escapeHtml(error.message)}</div>`;
  }
}

function renderTracked(request) {
  const history = (request.history || []).map((item) => `
    <div class="timeline-item"><span class="timeline-dot"></span><div>
      <strong>${escapeHtml(item.label)}</strong>
      <p>${escapeHtml(fmtDate(item.createdAt, true))}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</p>
    </div></div>`).join("");
  const allocation = request.allocation
    ? `<div class="notice notice-info"><strong>${escapeHtml(request.allocation.centreName || request.allocation.centreId)}</strong>
       · ${escapeHtml(resourceSummary(request.allocation.items))} · ${escapeHtml(request.allocation.status)}</div>`
    : "";
  $("#trackResult").innerHTML = `<div class="stack">
    <div class="between"><div><span class="hint">${escapeHtml(request.id)}</span><h2>${escapeHtml(request.typeLabel)} at ${escapeHtml(request.locationName)}</h2></div>
      ${statusBadge(request.status, request.statusLabel)}</div>
    <p class="small muted">${escapeHtml(request.description)}</p>
    ${allocation}
    <div><div class="section-title">History</div><div class="timeline">${history || '<p class="muted small">No history recorded.</p>'}</div></div>
  </div>`;
}

async function init() {
  setupNavigation();
  setupReport();
  setupNearby();
  setupTrack();
  state.homeMap = new MapView("homeMap", { center: [30.3165, 78.0322], zoom: 10 });
  await loadOverview();
  showView(location.hash.slice(1) || "home");
}

init();
