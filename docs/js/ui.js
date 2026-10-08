// Pure rendering/DOM logic — kept separate from business logic (managers).

export function el(id) { return document.getElementById(id); }

export function showToast(message, isError = false) {
  alert((isError ? "⚠ " : "✅ ") + message);
}

export function renderStats(stats) {
  const grid = el("statsGrid");
  const cards = [
    ["Active Disasters", stats.activeDisasters],
    ["Critical Disasters", stats.criticalDisasters],
    ["Resolved Disasters", stats.resolvedDisasters],
    ["People Affected", stats.peopleAffected.toLocaleString()],
    ["Available Resources", stats.availableResources],
    ["Dispatched Resources", stats.dispatchedResources],
    ["Total Allocations", stats.totalAllocations],
    ["Avg. Response Distance", stats.avgDistance.toFixed(2) + " km"],
  ];
  grid.innerHTML = cards.map(([label, value]) =>
    `<div class="stat-card"><div class="value">${value}</div><div class="label">${label}</div></div>`
  ).join("");
}

export function renderDisasterList(disasters) {
  const container = el("disasterList");
  if (!disasters.length) { container.innerHTML = "<p>No active disasters.</p>"; return; }
  container.innerHTML = disasters.map((d) => `
    <div class="record-card sev-${d.severity}">
      <strong>${d.id}</strong> — ${d.type} <span class="badge ${d.status}">${d.status}</span><br>
      Severity: <b>${d.severity}</b> | Affected: ${d.affectedPeople}<br>
      Location: ${d.locationName} (${d.latitude.toFixed(4)}, ${d.longitude.toFixed(4)})<br>
      Required: ${d.requiredResources.join(", ") || "None"}<br>
      <small>Reported: ${d.timestamp}</small>
    </div>
  `).join("");
}

export function renderResourceTable(resources) {
  const tbody = document.querySelector("#resourceTable tbody");
  tbody.innerHTML = resources.map((r) => `
    <tr>
      <td>${r.id}</td><td>${r.category}</td><td>${r.type}</td><td>${r.quantity}</td>
      <td><span class="badge ${r.status}">${r.status}</span></td>
      <td>${r.locationName}</td><td>${r.priority}</td>
      <td><button class="btn toggle-status" data-id="${r.id}" data-status="${r.status}">Toggle Status</button></td>
    </tr>
  `).join("");
}

export function renderHospitalTable(hospitals) {
  const tbody = document.querySelector("#hospitalTable tbody");
  tbody.innerHTML = hospitals.map((h) => `
    <tr><td>${h.id}</td><td>${h.name}</td><td>${h.totalBeds}</td><td>${h.availableBeds}</td><td>${h.emergencyCapacity}</td></tr>
  `).join("");
}

export function renderShelterTable(shelters) {
  const tbody = document.querySelector("#shelterTable tbody");
  tbody.innerHTML = shelters.map((s) => `
    <tr><td>${s.id}</td><td>${s.name}</td><td>${s.capacity}</td><td>${s.occupied}</td><td>${s.availableCapacity}</td></tr>
  `).join("");
}

export function renderAllocationTable(history) {
  const tbody = document.querySelector("#allocationTable tbody");
  tbody.innerHTML = history.map((a) => `
    <tr><td>${a.allocationId}</td><td>${a.disasterId}</td><td>${a.resourceId}</td>
    <td>${a.resourceCategory}</td><td>${a.distanceKm.toFixed(2)} km</td>
    <td><span class="badge ${a.status}">${a.status}</span></td></tr>
  `).join("");
}

export function populateSelect(selectEl, items, labelFn) {
  selectEl.innerHTML = items.map((item) => `<option value="${item.id}">${labelFn(item)}</option>`).join("");
}

export function populateLocationSelect(selectEl, locations) {
  selectEl.innerHTML = locations.map((loc) => `<option value="${loc}">${loc}</option>`).join("");
}

export function showDistanceAnalysis(container, title, lines) {
  container.innerHTML = `<div class="result-box">-----------------------------------------\n${title}\n-----------------------------------------\n${lines.join("\n")}\n-----------------------------------------</div>`;
}
