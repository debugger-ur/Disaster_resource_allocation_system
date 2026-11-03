import { api } from "./api.js";
import { DrrasMap, CATEGORY_META } from "./map.js";
import { buildTrackSteps } from "./shared.js";
import {
  qs,
  qsa,
  el,
  esc,
  icon,
  debounce,
  fmtDateTime,
  fmtNumber,
  fmtDistance,
  fmtDuration,
  fmtBytes,
  titleCase,
  statusBadge,
  severityBadge,
  availabilityBadge,
  resourceLabel,
  itemsSummary,
  copyText,
  readFileAsDataUrl,
  STATUS_META,
} from "./format.js";

/* ------------------------------------------------------------------ */
/* State                                                              */
/* ------------------------------------------------------------------ */

const DEFAULT_ORIGIN = { latitude: 30.3165, longitude: 78.0322, label: "Dehradun city centre" };
const RECENT_KEY = "drras_recent_request_ids";
const MAX_FILES = 3;

const state = {
  health: null,
  overview: null,
  origin: { ...DEFAULT_ORIGIN },
  category: "all",
  radius: 25,
  resource: "",
  openOnly: true,
  centres: [],
  selectedCentre: null,
  routesByCentre: new Map(),
  incidents: [],
  files: [],
  reportPin: null,
  serviceDown: false,
};

const maps = { overview: null, report: null, nearby: null };

/* ------------------------------------------------------------------ */
/* Bootstrap                                                           */
/* ------------------------------------------------------------------ */

document.addEventListener("DOMContentLoaded", () => {
  wireNav();
  wireHeader();
  initRouter();
  checkHealth();
  initOverview();
  initReportForm();
  initNearby();
  initTrack();
});

function wireHeader() {
  const toggle = qs("#navToggle");
  const nav = qs("#siteNav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }
  document.addEventListener("click", (event) => {
    if (event.target.closest(".suggestions")) return;
    qsa(".suggestions").forEach((box) => {
      box.hidden = true;
    });
  });
}

async function checkHealth() {
  try {
    state.health = await api.health();
  } catch (error) {
    state.serviceDown = true;
    state.health = null;
    const banner = el("div", "notice notice--danger");
    banner.style.margin = "16px 0 0";
    banner.innerHTML = `<svg width="18" height="18" aria-hidden="true"><use href="#i-alert"/></svg>
      <span><strong>The reporting service is not reachable.</strong> ${esc(error.message)}
      Start it with <span class="mono">python3 backend/admin_server.py</span>. For an emergency, call 112.</span>`;
    const main = qs("#main");
    if (main) main.prepend(banner);
    const submit = qs("#reportSubmit");
    if (submit) submit.disabled = true;
  }
}

function wireNav() {
  document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-nav]");
    if (!link) return;
    event.preventDefault();
    const view = link.dataset.nav;
    if (location.hash !== `#${view}`) {
      history.pushState(null, "", `#${view}`);
    }
    showView(view);
    const nav = qs("#siteNav");
    if (nav?.classList.contains("is-open")) {
      nav.classList.remove("is-open");
      qs("#navToggle")?.setAttribute("aria-expanded", "false");
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  window.addEventListener("hashchange", () => {
    const view = parseHash().view;
    showView(view);
  });
}

function parseHash() {
  const raw = location.hash.replace(/^#/, "");
  const [view, param] = raw.split("/");
  const known = ["overview", "report", "nearby", "track", "how"];
  return { view: known.includes(view) ? view : "overview", param: param || null };
}

function initRouter() {
  const { view, param } = parseHash();
  showView(view);
  if (view === "track" && param) {
    const input = qs("#trackId");
    if (input) input.value = decodeURIComponent(param);
    loadTrackedRequest(decodeURIComponent(param));
  }
}

function showView(view) {
  qsa(".view").forEach((section) => {
    section.hidden = section.dataset.view !== view;
  });
  qsa("[data-nav]").forEach((link) => {
    if (link.dataset.nav === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.title =
    {
      overview: "DRRAS — Disaster Relief Resource Allocation System",
      report: "Report an emergency · DRRAS",
      nearby: "Nearby help centres · DRRAS",
      track: "Track your request · DRRAS",
      how: "How DRRAS works · DRRAS",
    }[view] || "DRRAS";
  requestAnimationFrame(() => {
    Object.values(maps).forEach((map) => map?.invalidate());
  });
}

/* ------------------------------------------------------------------ */
/* Overview                                                           */
/* ------------------------------------------------------------------ */

async function initOverview() {
  const map = new DrrasMap(qs("#overviewMap"), { zoom: 11 });
  maps.overview = map;
  await loadOverview();
}

async function loadOverview() {
  try {
    const data = await api.overview();
    state.overview = data;
    state.incidents = data.incidents || [];
    renderOverview(data);
  } catch (error) {
    const host = qs("#overviewIncidents");
    if (host) {
      host.innerHTML = `<div class="empty"><h3>Live data unavailable</h3><p>${esc(error.message)}</p></div>`;
    }
  }
}

function renderOverview(data) {
  const stats = data.stats || {};
  setText("#statActive", fmtNumber(stats.activeIncidents ?? 0));
  setText("#statCentres", fmtNumber(stats.centresOnline ?? 0));
  setText("#statCentresMeta", `of ${fmtNumber(stats.centresTotal ?? 0)} registered centres`);
  setText("#statPeople", fmtNumber(stats.peopleReached ?? 0));
  setText("#statResolved", fmtNumber(stats.requestsResolved ?? 0));
  setText(
    "#statResolvedMeta",
    `${fmtNumber(stats.requestsTotal ?? 0)} request${stats.requestsTotal === 1 ? "" : "s"} received in total`,
  );

  const incidentHost = qs("#overviewIncidents");
  if (incidentHost) {
    if (!data.incidents?.length) {
      incidentHost.innerHTML = `<div class="empty">
        <svg width="30" height="30" aria-hidden="true"><use href="#i-shield"/></svg>
        <h3>No active incidents</h3>
        <p>Approved reports under response will appear here. You can still report an emergency or browse help centres.</p>
      </div>`;
    } else {
      incidentHost.innerHTML = `<ul class="list">${data.incidents
        .map(
          (incident) => `<li>
            <button class="centre-card" type="button" data-incident="${esc(incident.id)}">
              <span class="centre-card__icon" style="color:${CATEGORY_META.incident.color}">
                ${icon("alert", 19)}
              </span>
              <span>
                <span class="centre-card__name">${esc(incident.locationName || "Incident")}</span>
                <span class="centre-card__meta">${esc(titleCase(incident.type))} · ${fmtNumber(incident.affectedPeople)} people affected</span>
                <span class="flex flex-wrap" style="gap:6px;margin-top:6px">
                  ${severityBadge(incident.severity)}
                  ${statusBadge(incident.workflowStatus)}
                  <span class="tiny muted">${esc(fmtDateTime(incident.submittedAt))}</span>
                </span>
              </span>
              <span class="centre-card__right">
                <span class="chevron">${icon("chevron", 17)}</span>
              </span>
            </button>
          </li>`,
        )
        .join("")}</ul>`;
      qsa("[data-incident]", incidentHost).forEach((button) => {
        button.addEventListener("click", () => {
          const incident = state.incidents.find((item) => item.id === button.dataset.incident);
          if (!incident) return;
          setOrigin(
            { latitude: incident.latitude, longitude: incident.longitude, label: incident.locationName },
            { navigate: true },
          );
        });
      });
    }
  }

  const dispatchHost = qs("#overviewDispatches");
  if (dispatchHost) {
    if (!data.recentDispatches?.length) {
      dispatchHost.innerHTML = `<div class="empty" style="padding:28px"><h3>No dispatches yet</h3><p>Allocations appear here once a coordinator assigns resources.</p></div>`;
    } else {
      dispatchHost.innerHTML = `<ul class="list list--divide">${data.recentDispatches
        .map(
          (dispatch) => `<li style="padding:13px 18px">
            <div class="between" style="gap:8px">
              <strong style="font-size:0.84rem">${esc(dispatch.centreName)}</strong>
              <span class="badge badge--neutral">${esc(titleCase(dispatch.status))}</span>
            </div>
            <div class="small muted" style="margin-top:3px">${esc(itemsSummary(dispatch.items))}</div>
            <div class="tiny muted" style="margin-top:4px">${esc(dispatch.requestId)} · ${esc(fmtDateTime(dispatch.createdAt))}</div>
          </li>`,
        )
        .join("")}</ul>`;
    }
  }

  const map = maps.overview;
  if (map?.ready) {
    map.setIncidents(data.incidents || [], {
      onClick: (incident) => {
        setOrigin(
          { latitude: incident.latitude, longitude: incident.longitude, label: incident.locationName },
          { navigate: true },
        );
      },
    });
    map.setCentres(data.centres || [], { onClick: (centre) => openNearbyAtCentre(centre) });
    const points = [
      ...(data.incidents || []).map((item) => [item.latitude, item.longitude]),
      ...(data.centres || []).map((item) => [item.latitude, item.longitude]),
    ];
    if (points.length) map.fit(points, { padding: [30, 30], maxZoom: 12 });
    setText("#overviewMapCount", `${data.incidents?.length || 0} active · ${data.centres?.length || 0} centres`);
  }
}

function setText(selector, text) {
  const node = qs(selector);
  if (node) node.textContent = String(text);
}

/* ------------------------------------------------------------------ */
/* Report form                                                        */
/* ------------------------------------------------------------------ */

function initReportForm() {
  const form = qs("#reportForm");
  if (!form) return;

  const description = qs("#rDescription");
  description?.addEventListener("input", () => {
    setText("#rDescriptionCount", `${description.value.length} / 2000`);
  });

  qsa("[data-qty]").forEach((input) => {
    input.addEventListener("input", () => {
      const checkbox = qs(`[data-resource="${input.dataset.qty}"]`);
      if (Number(input.value) > 0 && checkbox) checkbox.checked = true;
    });
  });

  const reportMap = new DrrasMap(qs("#reportMap"), { zoom: 12 });
  maps.report = reportMap;
  if (reportMap.ready) {
    reportMap.onMapClick((latlng) => setReportPin(latlng.lat, latlng.lng, { pan: false }));
    reportMap.setPickerMarker(DEFAULT_ORIGIN.latitude, DEFAULT_ORIGIN.longitude, {
      draggable: true,
      onMove: (lat, lon) => setReportPin(lat, lon, { pan: false, keepMarker: true }),
    });
    setReportPin(DEFAULT_ORIGIN.latitude, DEFAULT_ORIGIN.longitude, { pan: false, keepMarker: true, silent: true });
  }

  wirePlaceSearch(qs("#rPlaceSearch"), qs("#rPlaceSuggestions"), (place) => {
    setReportPin(place.latitude, place.longitude, { pan: true, zoom: 14 });
    const nameInput = qs("#rLocation");
    if (nameInput) nameInput.value = place.shortName || place.name;
    reportMap?.focus(place.latitude, place.longitude, 14);
  });

  qs("#rGeolocate")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    await useGeolocation({
      button,
      onSuccess: (coords) => {
        setReportPin(coords.latitude, coords.longitude, { pan: true, zoom: 15 });
        const name = qs("#rLocation");
        if (name && !name.value.trim()) name.value = "My current location";
        reportMap?.focus(coords.latitude, coords.longitude, 15);
      },
      onError: (message) => setLocationStatus(message, true),
    });
  });

  wireFilePicker();
  loadReserveHint();

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitReport(form);
  });

  qs("#reportResult")?.addEventListener("click", (event) => {
    const copy = event.target.closest("[data-copy]");
    if (copy) {
      copyText(copy.dataset.copy).then((ok) => {
        if (ok) {
          copy.textContent = "Copied";
          setTimeout(() => {
            copy.textContent = "Copy";
          }, 1800);
        }
      });
    }
    const track = event.target.closest("[data-track]");
    if (track) {
      history.pushState(null, "", `#track/${encodeURIComponent(track.dataset.track)}`);
      showView("track");
      const input = qs("#trackId");
      if (input) input.value = track.dataset.track;
      loadTrackedRequest(track.dataset.track);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    const another = event.target.closest("[data-report-another]");
    if (another) {
      resetReportForm();
    }
  });
}

function setReportPin(lat, lon, { pan = true, zoom = 14, keepMarker = false, silent = false } = {}) {
  state.reportPin = { latitude: Number(lat), longitude: Number(lon) };
  const latInput = qs("#rLat");
  const lonInput = qs("#rLon");
  if (latInput) latInput.value = Number(lat).toFixed(6);
  if (lonInput) lonInput.value = Number(lon).toFixed(6);
  if (!silent) {
    setLocationStatus(
      `Pin dropped at ${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}. Check that it matches the location name.`,
      false,
    );
  }
  const map = maps.report;
  if (!map?.ready) return;
  if (keepMarker) {
    map.movePicker(Number(lat), Number(lon));
  } else {
    map.setPickerMarker(Number(lat), Number(lon), {
      draggable: true,
      onMove: (nextLat, nextLon) => setReportPin(nextLat, nextLon, { pan: false, keepMarker: true }),
    });
  }
  if (pan) map.focus(Number(lat), Number(lon), zoom);
}

function setLocationStatus(message, isError) {
  const node = qs("#rLocationStatus");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("text-danger", Boolean(isError));
}

function wirePlaceSearch(input, box, onPick) {
  if (!input || !box) return;
  const run = debounce(async (query) => {
    if (query.trim().length < 2) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    try {
      const { results } = await api.places(query);
      if (!results?.length) {
        box.innerHTML = `<div style="padding:10px 12px;font-size:0.8rem;color:var(--muted)">No places found. You can also click the map to drop a pin.</div>`;
        box.hidden = false;
        return;
      }
      box.innerHTML = results
        .map(
          (place, index) => `<button type="button" data-place="${index}">
            <span>${esc(place.shortName || place.name)}</span>
            <small>${esc(place.name)}${place.source === "local" ? " · local gazetteer" : " · OpenStreetMap"}</small>
          </button>`,
        )
        .join("");
      box.hidden = false;
      qsa("[data-place]", box).forEach((button) => {
        button.addEventListener("click", () => {
          const place = results[Number(button.dataset.place)];
          box.hidden = true;
          box.innerHTML = "";
          input.value = place.shortName || place.name;
          onPick(place);
        });
      });
    } catch {
      box.hidden = true;
    }
  }, 320);
  input.addEventListener("input", () => run(input.value));
  input.addEventListener("focus", () => {
    if (box.innerHTML && input.value.trim().length >= 2) box.hidden = false;
  });
}

async function useGeolocation({ button, onSuccess, onError }) {
  if (!navigator.geolocation) {
    onError("This browser does not support location access. Search for a place or click the map instead.");
    return;
  }
  const original = button?.innerHTML;
  if (button) {
    button.disabled = true;
    button.innerHTML = `<span class="spinner spinner--dark"></span> Locating…`;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => {
      if (button) {
        button.disabled = false;
        button.innerHTML = original;
      }
      onSuccess({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
      });
    },
    (error) => {
      if (button) {
        button.disabled = false;
        button.innerHTML = original;
      }
      const message =
        error.code === error.PERMISSION_DENIED
          ? "Location permission was denied. Search for a place or click the map instead."
          : "Your location could not be determined. Search for a place or click the map instead.";
      onError(message);
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
  );
}

function wireFilePicker() {
  const input = qs("#rFiles");
  const drop = qs("#rFileDrop");
  if (!input) return;
  input.addEventListener("change", () => addFiles(Array.from(input.files || [])));
  if (drop) {
    ["dragenter", "dragover"].forEach((name) =>
      drop.addEventListener(name, (event) => {
        event.preventDefault();
        drop.classList.add("is-dragover");
      }),
    );
    ["dragleave", "drop"].forEach((name) =>
      drop.addEventListener(name, (event) => {
        event.preventDefault();
        drop.classList.remove("is-dragover");
      }),
    );
    drop.addEventListener("drop", (event) => addFiles(Array.from(event.dataTransfer?.files || [])));
  }
}

function addFiles(files) {
  const allowed = ["image/jpeg", "image/png", "application/pdf"];
  for (const file of files) {
    if (state.files.length >= MAX_FILES) {
      showReportError(`You can attach up to ${MAX_FILES} files.`);
      break;
    }
    if (!allowed.includes(file.type)) {
      showReportError(`${file.name} is not a JPEG, PNG or PDF.`);
      continue;
    }
    if (file.size > 5 * 1024 * 1024) {
      showReportError(`${file.name} is larger than 5 MB.`);
      continue;
    }
    state.files.push(file);
  }
  renderFileList();
  const input = qs("#rFiles");
  if (input) input.value = "";
}

function renderFileList() {
  const host = qs("#rEvidenceList");
  if (!host) return;
  host.innerHTML = state.files
    .map((file, index) => {
      const preview =
        file.type.startsWith("image/") && file.__preview
          ? `<img src="${file.__preview}" alt="">`
          : `<span class="badge badge--neutral" style="font-size:0.62rem">${file.type === "application/pdf" ? "PDF" : "IMG"}</span>`;
      return `<span class="evidence-chip" title="${esc(file.name)}">
        ${preview}
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:170px">${esc(file.name)}</span>
        <span class="muted tiny">${fmtBytes(file.size)}</span>
        <button type="button" data-remove-file="${index}" aria-label="Remove ${esc(file.name)}">✕</button>
      </span>`;
    })
    .join("");
  qsa("[data-remove-file]", host).forEach((button) => {
    button.addEventListener("click", () => {
      state.files.splice(Number(button.dataset.removeFile), 1);
      renderFileList();
    });
  });
  state.files.forEach((file) => {
    if (file.type.startsWith("image/") && !file.__preview) {
      readFileAsDataUrl(file)
        .then((dataUrl) => {
          file.__preview = dataUrl;
          renderFileList();
        })
        .catch(() => {});
    }
  });
}

function collectReportPayload() {
  const type = qs("#rType").value;
  const severity = qs('input[name="rSeverity"]:checked')?.value || "LOW";
  const affectedPeople = Number(qs("#rAffected").value || 0);
  const description = qs("#rDescription").value.trim();
  const locationName = qs("#rLocation").value.trim();
  const latitude = Number(qs("#rLat").value);
  const longitude = Number(qs("#rLon").value);
  const contactName = qs("#rContactName").value.trim();
  const contactPhone = qs("#rContactPhone").value.trim();
  const contactEmail = qs("#rContactEmail").value.trim();

  const requiredResources = [];
  const resourceQuantities = {};
  qsa("[data-resource]").forEach((checkbox) => {
    const category = checkbox.dataset.resource;
    const qtyInput = qs(`[data-qty="${category}"]`);
    const qty = Number(qtyInput?.value || 0);
    if (checkbox.checked || qty > 0) {
      requiredResources.push(category);
      if (qty > 0) resourceQuantities[category] = Math.trunc(qty);
    }
  });

  const problems = [];
  if (!locationName) problems.push("Add a location name.");
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    problems.push("Place the location on the map (or use your GPS) so the request can be routed.");
  }
  if (description.length < 20) problems.push("Describe what is happening in at least 20 characters.");
  if (!Number.isFinite(affectedPeople) || affectedPeople < 0) problems.push("Affected people must be zero or more.");
  if (!contactPhone && !contactEmail) {
    problems.push("Add a phone number or email so a coordinator can verify the report.");
  }
  return {
    payload: {
      type,
      severity,
      affectedPeople: Math.trunc(affectedPeople),
      description,
      locationName,
      latitude,
      longitude,
      contactName,
      contactPhone,
      contactEmail,
      requiredResources,
      resourceQuantities,
      evidence: [],
    },
    problems,
  };
}

async function submitReport(form) {
  showReportError("");
  const submit = qs("#reportSubmit");
  const { payload, problems } = collectReportPayload();
  if (problems.length) {
    showReportError(problems.join(" "));
    return;
  }

  const original = submit.innerHTML;
  submit.disabled = true;
  submit.innerHTML = `<span class="spinner"></span> Submitting…`;

  try {
    if (state.files.length) {
      submit.innerHTML = `<span class="spinner"></span> Uploading evidence…`;
      const uploaded = [];
      for (const file of state.files) {
        const dataUrl = await readFileAsDataUrl(file);
        const base64 = dataUrl.split(",")[1] || "";
        const result = await api.uploadEvidence({
          fileName: file.name,
          mimeType: file.type,
          data: base64,
        });
        uploaded.push(result.evidence.id);
      }
      payload.evidence = uploaded;
    }
    submit.innerHTML = `<span class="spinner"></span> Verifying report…`;
    const response = await api.submitRequest(payload);
    const record = response.request;
    state.files = [];
    renderFileList();
    rememberRequest(record.id);
    renderReceipt(record, response.verification);
    submit.innerHTML = "Submitted";
    setTimeout(() => {
      submit.innerHTML = original;
      submit.disabled = false;
    }, 1200);
    qs("#reportResult")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    submit.disabled = false;
    submit.innerHTML = original;
    showReportError(error.message || "The report could not be submitted.");
  }
}

function showReportError(message) {
  const box = qs("#reportError");
  if (!box) return;
  box.hidden = !message;
  box.innerHTML = message
    ? `<svg width="17" height="17" aria-hidden="true"><use href="#i-alert"/></svg><span>${esc(message)}</span>`
    : "";
}

function renderReceipt(record, verification) {
  const host = qs("#reportResult");
  if (!host) return;
  const status = STATUS_META[record.workflowStatus] || {};
  host.hidden = false;
  host.innerHTML = `
    <div class="receipt">
      <div class="flex" style="gap:10px">
        <span style="color:var(--ok)">${icon("check-circle", 24)}</span>
        <div>
          <h2 style="font-size:1.1rem">Report received</h2>
          <p class="muted small">Keep this request ID. It is the key to tracking and updating this report.</p>
        </div>
      </div>
      <div class="receipt__id mt-16">
        ${esc(record.id)}
        <button class="copy-btn" type="button" data-copy="${esc(record.id)}">Copy</button>
        ${statusBadge(record.workflowStatus, { large: true })}
      </div>
      <div class="receipt__grid">
        <div class="receipt__item"><span>Incident</span>${esc(titleCase(record.type))} · ${esc(titleCase(record.severity))}</div>
        <div class="receipt__item"><span>Location</span>${esc(record.locationName)}</div>
        <div class="receipt__item"><span>Submitted</span>${esc(fmtDateTime(record.submittedAt))}</div>
      </div>
      <div class="notice notice--info mt-16">
        ${icon("info", 17)}
        <span>${esc(record.verification?.summary || verification?.summary || status.description || "Your report is queued for review.")}
        ${record.duplicateOf ? ` Possible match: <span class="mono">${esc(record.duplicateOf)}</span>.` : ""}</span>
      </div>
      <div class="btn-row mt-16">
        <button class="btn btn--primary btn--sm" type="button" data-track="${esc(record.id)}">Track this request</button>
        <button class="btn btn--secondary btn--sm" type="button" data-report-another>Report another emergency</button>
      </div>
    </div>`;
}

function resetReportForm() {
  const form = qs("#reportForm");
  form?.reset();
  state.files = [];
  renderFileList();
  qsa('input[name="rSeverity"]').forEach((input) => {
    input.checked = input.value === "CRITICAL";
  });
  setText("#rDescriptionCount", "0 / 2000");
  setReportPin(DEFAULT_ORIGIN.latitude, DEFAULT_ORIGIN.longitude, { pan: true, zoom: 12, keepMarker: true, silent: true });
  setLocationStatus("No pin placed yet — search for a place or click the map.", false);
  const result = qs("#reportResult");
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
  showReportError("");
  state.reportPin = null;
  qs("#rLat").value = "";
  qs("#rLon").value = "";
  maps.report?.clearPickerMarker();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function loadReserveHint() {
  try {
    const { inventory } = await api.inventory();
    const entries = Object.entries(inventory || {}).filter(([, value]) => Number(value) > 0);
    if (!entries.length) return;
    setText(
      "#reserveHint",
      "Central reserve: " + entries.map(([category, amount]) => `${resourceLabel(category)} ${amount}`).join(" · "),
    );
  } catch {
    /* the hint is optional */
  }
}

/* ------------------------------------------------------------------ */
/* Nearby help                                                        */
/* ------------------------------------------------------------------ */

function initNearby() {
  const map = new DrrasMap(qs("#nearbyMap"), { zoom: 12 });
  maps.nearby = map;

  qsa("#nCategories [data-category]").forEach((button) => {
    button.addEventListener("click", () => {
      state.category = button.dataset.category;
      qsa("#nCategories [data-category]").forEach((other) => {
        const active = other === button;
        other.classList.toggle("is-active", active);
        other.setAttribute("aria-pressed", String(active));
      });
      loadNearby();
    });
  });

  qs("#nRadius")?.addEventListener("change", (event) => {
    state.radius = Number(event.target.value);
    loadNearby();
  });
  qs("#nOpenOnly")?.addEventListener("change", (event) => {
    state.openOnly = event.target.checked;
    loadNearby();
  });
  qs("#nResource")?.addEventListener("change", (event) => {
    state.resource = event.target.value;
    loadNearby();
  });

  wirePlaceSearch(qs("#nSearch"), qs("#nSuggestions"), (place) => {
    setOrigin({ latitude: place.latitude, longitude: place.longitude, label: place.shortName || place.name });
  });

  qs("#nIncident")?.addEventListener("change", (event) => {
    const incident = state.incidents.find((item) => item.id === event.target.value);
    if (incident) {
      setOrigin(
        { latitude: incident.latitude, longitude: incident.longitude, label: incident.locationName },
        { keepSelect: true },
      );
    }
  });

  qs("#nGeolocate")?.addEventListener("click", async (event) => {
    await useGeolocation({
      button: event.currentTarget,
      onSuccess: (coords) => {
        setOrigin({ latitude: coords.latitude, longitude: coords.longitude, label: "My current location" });
      },
      onError: (message) => {
        setText("#nearbyMapNote", message);
      },
    });
  });

  qs("#nearbyList")?.addEventListener("click", (event) => {
    const card = event.target.closest("[data-centre]");
    if (card) selectCentre(card.dataset.centre);
  });

  qs("#nearbyDetail")?.addEventListener("click", (event) => {
    const routeButton = event.target.closest("[data-route]");
    if (routeButton) {
      routeToCentre(routeButton.dataset.route, routeButton);
    }
    const clear = event.target.closest("[data-clear-route]");
    if (clear) {
      maps.nearby?.clearRoute();
      state.selectedCentre = null;
      qsa("[data-centre]").forEach((node) => node.classList.remove("is-selected"));
      qs("#nearbyDetail").innerHTML = "";
      maps.nearby?.selectCentre(null);
    }
  });

  if (map.ready) {
    map.onMapClick((latlng) => {
      setOrigin({ latitude: latlng.lat, longitude: latlng.lng, label: "Map selection" });
    });
  }

  loadIncidentsForNearby();
  loadNearby();
}

async function loadIncidentsForNearby() {
  try {
    const overview = state.overview || (await api.overview());
    state.overview = overview;
    state.incidents = overview.incidents || [];
    const select = qs("#nIncident");
    if (select) {
      select.innerHTML =
        `<option value="">Choose an active incident…</option>` +
        state.incidents
          .map(
            (incident) =>
              `<option value="${esc(incident.id)}">${esc(incident.locationName)} · ${esc(titleCase(incident.type))}</option>`,
          )
          .join("");
    }
  } catch {
    const select = qs("#nIncident");
    if (select) select.innerHTML = `<option value="">Incidents unavailable</option>`;
  }
}

function setOrigin(origin, { navigate = false, keepSelect = false } = {}) {
  state.origin = origin;
  state.selectedCentre = null;
  const label = qs("#nOriginLabel");
  if (label) label.textContent = `Origin: ${origin.label || "selected location"}`;
  if (maps.nearby?.ready) {
    maps.nearby.setOrigin(origin.latitude, origin.longitude);
    maps.nearby.setRadius(origin.latitude, origin.longitude, state.radius);
    maps.nearby.clearRoute();
  }
  if (!keepSelect) {
    const select = qs("#nIncident");
    if (select) select.value = "";
  }
  const detail = qs("#nearbyDetail");
  if (detail) detail.innerHTML = "";
  if (navigate) {
    history.pushState(null, "", "#nearby");
    showView("nearby");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  loadNearby();
}

async function loadNearby() {
  const list = qs("#nearbyList");
  if (!list) return;
  list.innerHTML = `<div class="loading-block"><span class="spinner spinner--dark"></span> Finding nearby help…</div>`;
  try {
    const result = await api.nearby({
      lat: state.origin.latitude,
      lon: state.origin.longitude,
      category: state.category,
      radius: state.radius,
      availability: state.openOnly ? "open" : "all",
      resource: state.resource || undefined,
      limit: 30,
    });
    state.centres = result.centres || [];
    renderNearby(result);
  } catch (error) {
    list.innerHTML = `<div class="empty"><h3>Help centres could not be loaded</h3><p>${esc(error.message)}</p></div>`;
    setText("#nearbyCount", "Unavailable");
  }
}

function renderNearby(result) {
  const centres = result.centres || [];
  const routing = result.routing || {};
  const source = routing.resultSource || "estimate";
  setText(
    "#nearbyCount",
    `${centres.length} centre${centres.length === 1 ? "" : "s"} within ${state.radius} km of ${state.origin.label || "the selected origin"}`,
  );
  const sourceBadge = qs("#nearbySourceBadge");
  if (sourceBadge) {
    sourceBadge.textContent = source === "osrm" ? "OSRM road routing" : "Road estimates";
    sourceBadge.className = source === "osrm" ? "badge badge--ok" : "badge badge--warn";
  }
  const routingBadge = qs("#routingBadge");
  if (routingBadge) {
    routingBadge.textContent = source === "osrm" ? "Live OSRM routing" : "Routing unavailable · distances estimated";
    routingBadge.className = source === "osrm" ? "badge badge--ok badge--lg" : "badge badge--warn badge--lg";
  }
  setText("#nearbyMapNote", routing.note || "");

  const list = qs("#nearbyList");
  if (!list) return;
  if (!centres.length) {
    list.innerHTML = `<div class="empty">
      <svg width="30" height="30" aria-hidden="true"><use href="#i-pin"/></svg>
      <h3>No centres match these filters</h3>
      <p>Increase the radius, turn off the “open only” filter, or choose a different category.</p>
    </div>`;
  } else {
    list.innerHTML = `<ul class="list">${centres
      .map((centre) => {
        const meta = CATEGORY_META[centre.category] || CATEGORY_META.other;
        return `<li>
          <button class="centre-card" type="button" data-centre="${esc(centre.id)}">
            <span class="centre-card__icon" style="color:${meta.color}">${icon("pin", 19)}</span>
            <span>
              <span class="centre-card__name">${esc(centre.name)}</span>
              <span class="centre-card__meta">${esc(meta.label)} · ${esc(centre.address || "")}</span>
              <span class="flex flex-wrap" style="gap:6px;margin-top:6px">
                ${availabilityBadge(centre.availability)}
                <span class="stock-chips">${stockChips(centre.stock)}</span>
              </span>
            </span>
            <span class="centre-card__right">
              <span class="centre-card__distance">${fmtDistance(centre.distanceKm)}</span>
              <span class="centre-card__eta">${icon("clock", 12)} ${fmtDuration(centre.durationMin)}${centre.distanceSource === "estimate" ? " · est." : ""}</span>
              <span class="tiny muted">${esc(centre.bearing || "")}</span>
            </span>
          </button>
        </li>`;
      })
      .join("")}</ul>`;
  }

  const map = maps.nearby;
  if (map?.ready) {
    map.setCentres(centres, {
      onClick: (centre) => selectCentre(centre.id),
      selectedId: state.selectedCentre?.id || null,
    });
    map.setOrigin(state.origin.latitude, state.origin.longitude, { pan: false });
    map.setRadius(state.origin.latitude, state.origin.longitude, state.radius);
    const points = [
      [state.origin.latitude, state.origin.longitude],
      ...centres.slice(0, 12).map((centre) => [centre.latitude, centre.longitude]),
    ];
    if (!state.selectedCentre) map.fit(points, { maxZoom: 13, padding: [36, 36] });
  }
}

function stockChips(stock) {
  const entries = Object.entries(stock || {}).filter(([, value]) => Number(value) > 0);
  if (!entries.length) return `<span class="stock-chip">No stock recorded</span>`;
  return entries
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(0, 3)
    .map(([category, amount]) => `<span class="stock-chip">${esc(resourceLabel(category))} ${fmtNumber(amount)}</span>`)
    .join("");
}

function selectCentre(centreId) {
  const centre = state.centres.find((item) => item.id === centreId);
  if (!centre) return;
  state.selectedCentre = centre;
  qsa("[data-centre]").forEach((node) => {
    node.classList.toggle("is-selected", node.dataset.centre === centreId);
  });
  maps.nearby?.selectCentre(centreId);
  maps.nearby?.focus(centre.latitude, centre.longitude, 14);
  const meta = CATEGORY_META[centre.category] || CATEGORY_META.other;
  const detail = qs("#nearbyDetail");
  if (!detail) return;
  detail.innerHTML = `<section class="card">
    <div class="card__head">
      <div>
        <p class="eyebrow">${esc(meta.label)}</p>
        <h2 class="card__title mt-8">${esc(centre.name)}</h2>
        <p class="card__sub">${esc(centre.address || "Address not recorded")}</p>
      </div>
      ${availabilityBadge(centre.availability)}
    </div>
    <div class="card__body stack" style="gap:14px">
      <div class="receipt__grid" style="margin-top:0">
        <div class="receipt__item"><span>Road distance</span>${fmtDistance(centre.distanceKm)} ${centre.distanceSource === "estimate" ? '<span class="badge badge--warn" style="margin-left:4px">estimated</span>' : '<span class="badge badge--ok" style="margin-left:4px">routed</span>'}</div>
        <div class="receipt__item"><span>Travel time</span>${fmtDuration(centre.durationMin)}</div>
        <div class="receipt__item"><span>Direction</span>${esc(titleCase(centre.bearing || "—"))}</div>
      </div>
      <div>
        <p class="tiny muted" style="margin-bottom:5px">Available resources</p>
        <div class="chip-row">${stockChips(centre.stock)}</div>
      </div>
      ${centre.capacityNote ? `<p class="small muted"><strong>Capacity note:</strong> ${esc(centre.capacityNote)}</p>` : ""}
      <div class="btn-row">
        <button class="btn btn--primary btn--sm" type="button" data-route="${esc(centre.id)}">
          ${icon("nav", 15)} Show route from origin
        </button>
        ${centre.phone ? `<a class="btn btn--secondary btn--sm" href="tel:${esc(centre.phone.replaceAll(" ", ""))}">${icon("phone", 15)} ${esc(centre.phone)}</a>` : ""}
        <a class="btn btn--ghost btn--sm" target="_blank" rel="noopener"
           href="https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=${state.origin.latitude}%2C${state.origin.longitude}%3B${centre.latitude}%2C${centre.longitude}">
          Open directions ${icon("arrow", 15)}
        </a>
        <button class="btn btn--ghost btn--sm" type="button" data-clear-route>Close</button>
      </div>
      <div id="routeStatus" class="small muted"></div>
    </div>
  </section>`;
  qs("#nearbyDetail")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function routeToCentre(centreId, button) {
  const centre = state.centres.find((item) => item.id === centreId);
  if (!centre) return;
  const status = qs("#routeStatus");
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span> Routing…`;
  try {
    const route = await api.route(
      state.origin.latitude,
      state.origin.longitude,
      centre.latitude,
      centre.longitude,
    );
    if (Array.isArray(route.geometry) && route.geometry.length > 1) {
      maps.nearby?.addRoute(route.geometry, { fit: true });
      if (status) {
        status.innerHTML = `<span class="text-ok"><strong>${fmtDistance(route.distanceKm)}</strong> · ${fmtDuration(route.durationMin)}</span> — road route from OSRM.`;
      }
    } else {
      maps.nearby?.clearRoute();
      if (status) {
        status.innerHTML = `<span class="text-warn">Live routing is unavailable, so no route line is drawn.</span> Estimated road distance is ${fmtDistance(route.distanceKm)} (${fmtDuration(route.durationMin)}). Use “Open directions” for a live route.`;
      }
    }
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

function openNearbyAtCentre(centre) {
  setOrigin(
    { latitude: centre.latitude, longitude: centre.longitude, label: centre.name },
    { navigate: true },
  );
  setTimeout(() => selectCentre(centre.id), 350);
}

/* ------------------------------------------------------------------ */
/* Track                                                              */
/* ------------------------------------------------------------------ */

function initTrack() {
  qs("#trackForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const id = qs("#trackId").value.trim();
    if (!id) return;
    history.replaceState(null, "", `#track/${encodeURIComponent(id)}`);
    loadTrackedRequest(id);
  });
  renderRecentIds();
  qs("#recentIdsList")?.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-recent-id]");
    if (!chip) return;
    const input = qs("#trackId");
    if (input) input.value = chip.dataset.recentId;
    history.replaceState(null, "", `#track/${encodeURIComponent(chip.dataset.recentId)}`);
    loadTrackedRequest(chip.dataset.recentId);
  });
}

function rememberRequest(id) {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list = raw ? JSON.parse(raw) : [];
    const next = [id, ...list.filter((item) => item !== id)].slice(0, 5);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage may be unavailable */
  }
  renderRecentIds();
}

function renderRecentIds() {
  const host = qs("#recentIds");
  const list = qs("#recentIdsList");
  if (!host || !list) return;
  let ids = [];
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    ids = raw ? JSON.parse(raw) : [];
  } catch {
    ids = [];
  }
  if (!Array.isArray(ids) || !ids.length) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  list.innerHTML = ids
    .map((id) => `<button class="chip chip--soft mono" type="button" data-recent-id="${esc(id)}">${esc(id)}</button>`)
    .join("");
}

async function loadTrackedRequest(id) {
  const host = qs("#trackResult");
  if (!host) return;
  host.innerHTML = `<section class="card card__pad"><div class="loading-block"><span class="spinner spinner--dark"></span> Loading request…</div></section>`;
  try {
    const { request } = await api.requestStatus(id);
    renderTrackedRequest(request);
  } catch (error) {
    host.innerHTML = `<section class="card card__pad">
      <div class="empty">
        <svg width="32" height="32" aria-hidden="true"><use href="#i-search"/></svg>
        <h3>Request not found</h3>
        <p>${esc(error.message)} Check the ID and try again. IDs look like <span class="mono">REQ-1A2B3C4D5E</span>.</p>
      </div>
    </section>`;
  }
}

function renderTrackedRequest(request) {
  const host = qs("#trackResult");
  if (!host) return;
  const meta = STATUS_META[request.workflowStatus] || {};
  const steps = buildTrackSteps(request.workflowStatus);
  const notifications = request.notifications || [];
  const allocations = request.allocations || [];

  host.innerHTML = `<section class="card">
    <div class="card__head">
      <div>
        <p class="eyebrow">Request ${esc(request.id)}</p>
        <h2 class="card__title mt-8">${esc(request.locationName)}</h2>
        <p class="card__sub">${esc(titleCase(request.type))} · submitted ${esc(fmtDateTime(request.submittedAt))}</p>
      </div>
      <div class="flex flex-wrap" style="gap:6px">${severityBadge(request.severity)}${statusBadge(request.workflowStatus, { large: true })}</div>
    </div>
    <div class="card__body stack">
      <div class="notice notice--info">
        ${icon("info", 17)}
        <span><strong>${esc(meta.label || titleCase(request.workflowStatus))}.</strong> ${esc(request.verification?.summary || meta.description || "")}
        ${request.duplicateOf ? `A similar report exists: <span class="mono">${esc(request.duplicateOf)}</span>. A coordinator will merge, link or keep both.` : ""}</span>
      </div>

      ${request.decisionMessage ? `<div class="notice ${request.workflowStatus === "rejected" ? "notice--danger" : "notice--ok"}">
        ${icon(request.workflowStatus === "rejected" ? "alert" : "check-circle", 17)}
        <span><strong>Message from the command centre.</strong><br>${esc(request.decisionMessage)}</span>
      </div>` : ""}

      <div class="receipt__grid" style="margin-top:0">
        <div class="receipt__item"><span>People affected</span>${fmtNumber(request.affectedPeople)}</div>
        <div class="receipt__item"><span>Resources requested</span>${esc(itemsSummary(request.resourceQuantities)) || esc((request.requiredResources || []).map(resourceLabel).join(" · ") || "—")}</div>
        <div class="receipt__item"><span>Last update</span>${esc(fmtDateTime(request.updatedAt))}</div>
      </div>

      <div>
        <p class="drawer-section__title" style="margin-bottom:10px">Status timeline</p>
        <div class="stepper">
          ${steps
            .map(
              (step) => `<div class="step ${step.state === "done" ? "is-done" : step.state === "current" ? "is-current" : "is-pending"}">
                <span class="step__dot">${step.state === "done" ? icon("check", 13) : step.index}</span>
                <span>
                  <span class="step__title">${esc(step.label)}</span>
                  ${step.note ? `<span class="step__desc">${esc(step.note)}</span>` : ""}
                </span>
              </div>`,
            )
            .join("")}
        </div>
      </div>

      ${
        allocations.length
          ? `<div>
              <p class="drawer-section__title" style="margin-bottom:8px">Resources assigned</p>
              <ul class="list list--divide">
                ${allocations
                  .map(
                    (allocation) => `<li style="padding:10px 0">
                      <div class="between" style="gap:8px">
                        <strong style="font-size:0.86rem">${esc(allocation.centreName)}</strong>
                        <span class="badge badge--neutral">${esc(titleCase(allocation.status))}</span>
                      </div>
                      <div class="small muted" style="margin-top:2px">${esc(itemsSummary(allocation.items))}</div>
                      <div class="tiny muted" style="margin-top:2px">
                        ${fmtDistance(allocation.distanceKm)} · ${fmtDuration(allocation.durationMin)}${allocation.distanceSource === "estimate" ? " (estimated)" : ""}
                        ${allocation.centrePhone ? ` · <a href="tel:${esc(allocation.centrePhone.replaceAll(" ", ""))}">${esc(allocation.centrePhone)}</a>` : ""}
                      </div>
                    </li>`,
                  )
                  .join("")}
              </ul>
            </div>`
          : ""
      }

      ${
        notifications.length
          ? `<div>
              <p class="drawer-section__title" style="margin-bottom:8px">Updates</p>
              <ul class="timeline">
                ${notifications
                  .slice()
                  .reverse()
                  .map(
                    (item) => `<li>
                      <div class="timeline__time">${esc(fmtDateTime(item.createdAt))}</div>
                      <div class="timeline__text">${esc(item.message)}</div>
                    </li>`,
                  )
                  .join("")}
              </ul>
            </div>`
          : ""
      }
    </div>
  </section>`;
}
