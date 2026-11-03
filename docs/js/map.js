import { escapeHtml } from "./api.js";

const COLOURS = {
  hospital: "#175cd3",
  relief_camp: "#067647",
  food_water: "#b54708",
  rescue_team: "#9a3412",
  warehouse: "#475467",
  shelter: "#0e7090",
  medical_camp: "#c11574",
  other: "#667085",
  incident: "#bf2c2c",
  user: "#16794d",
};
const SYMBOLS = {
  hospital: "+", relief_camp: "C", food_water: "F", rescue_team: "R",
  warehouse: "W", shelter: "S", medical_camp: "M", other: "•",
};

function pinIcon(category, extraClass = "") {
  const colour = COLOURS[category] || COLOURS.other;
  const symbol = category === "incident" ? "!" : category === "user" ? "●" : (SYMBOLS[category] || "•");
  return window.L.divIcon({
    className: "",
    html: `<div class="marker-pin ${extraClass}" style="--marker:${colour}"><span>${symbol}</span></div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 29],
    popupAnchor: [0, -26],
  });
}

export class MapView {
  constructor(element, options = {}) {
    this.element = typeof element === "string" ? document.getElementById(element) : element;
    this.ready = false;
    this.markers = [];
    this.routeLine = null;
    this.pickerMarker = null;
    this.centreLayer = null;
    this.incidentLayer = null;
    if (!this.element) return;
    if (!window.L) {
      this.element.innerHTML = '<div class="map-fallback">Map library could not load. Centre lists and distances still work.</div>';
      return;
    }
    this.map = window.L.map(this.element, { scrollWheelZoom: false }).setView(
      options.center || [30.3165, 78.0322], options.zoom || 11,
    );
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(this.map);
    this.centreLayer = window.L.layerGroup().addTo(this.map);
    this.incidentLayer = window.L.layerGroup().addTo(this.map);
    this.ready = true;
    setTimeout(() => this.map.invalidateSize(), 80);
  }

  setCentres(centres, { onClick, selectedId } = {}) {
    if (!this.ready) return;
    this.centreLayer.clearLayers();
    this.markers = this.markers.filter((item) => item.kind !== "centre");
    (centres || []).forEach((centre) => {
      const marker = window.L.marker([centre.latitude, centre.longitude], {
        icon: pinIcon(centre.category, selectedId === centre.id ? "selected" : ""),
        title: centre.name,
      }).addTo(this.centreLayer);
      const stock = Object.entries(centre.stock || {}).slice(0, 4)
        .map(([name, amount]) => `${escapeHtml(name)}: ${Number(amount)}`).join(" · ");
      marker.bindPopup(
        `<strong>${escapeHtml(centre.name)}</strong><br>${escapeHtml(centre.categoryLabel || centre.category)}`
        + `<br>${escapeHtml(centre.availability)}${stock ? `<br><span class="small">${stock}</span>` : ""}`,
      );
      if (onClick) marker.on("click", () => onClick(centre));
      this.markers.push({ kind: "centre", id: centre.id, marker });
    });
  }

  setIncidents(incidents, { onClick } = {}) {
    if (!this.ready) return;
    this.incidentLayer.clearLayers();
    this.markers = this.markers.filter((item) => item.kind !== "incident");
    (incidents || []).forEach((incident) => {
      const marker = window.L.marker([incident.latitude, incident.longitude], {
        icon: pinIcon("incident", "incident"), title: incident.id,
      }).addTo(this.incidentLayer);
      marker.bindPopup(
        `<strong>${escapeHtml(incident.typeLabel || incident.disasterType)}</strong><br>`
        + `${escapeHtml(incident.locationName)}<br><span class="small">${escapeHtml(incident.id)}</span>`,
      );
      if (onClick) marker.on("click", () => onClick(incident));
      this.markers.push({ kind: "incident", id: incident.id, marker });
    });
  }

  setOrigin(latitude, longitude) {
    if (!this.ready) return;
    if (this.originMarker) this.map.removeLayer(this.originMarker);
    this.originMarker = window.L.marker([latitude, longitude], {
      icon: pinIcon("user", "user"), title: "Selected location",
    }).addTo(this.map);
  }

  pick(onPick) {
    if (!this.ready) return;
    const choose = (latlng) => {
      if (this.pickerMarker) this.map.removeLayer(this.pickerMarker);
      this.pickerMarker = window.L.marker(latlng, {
        icon: pinIcon("incident", "incident"), draggable: true,
      }).addTo(this.map);
      this.pickerMarker.on("dragend", () => onPick(this.pickerMarker.getLatLng()));
      onPick(latlng);
    };
    this.map.on("click", (event) => choose(event.latlng));
  }

  setPicker(latitude, longitude) {
    if (!this.ready) return;
    if (this.pickerMarker) this.map.removeLayer(this.pickerMarker);
    this.pickerMarker = window.L.marker([latitude, longitude], {
      icon: pinIcon("incident", "incident"), draggable: true,
    }).addTo(this.map);
    this.pickerMarker.on("dragend", () => {
      const point = this.pickerMarker.getLatLng();
      this.element.dispatchEvent(new CustomEvent("picker-move", {
        detail: { latitude: point.lat, longitude: point.lng },
      }));
    });
    this.focus(latitude, longitude, 13);
  }

  drawRoute(coordinates) {
    if (!this.ready || !coordinates || coordinates.length < 2) return false;
    this.clearRoute();
    this.routeLine = window.L.polyline(coordinates, {
      color: "#1d4ed8", weight: 4, opacity: 0.85,
    }).addTo(this.map);
    this.map.fitBounds(this.routeLine.getBounds(), { padding: [24, 24] });
    return true;
  }

  clearRoute() {
    if (this.ready && this.routeLine) {
      this.map.removeLayer(this.routeLine);
      this.routeLine = null;
    }
  }

  focus(latitude, longitude, zoom = 14) {
    if (this.ready) this.map.setView([latitude, longitude], zoom);
  }

  fitAll() {
    if (!this.ready || !this.markers.length) return;
    const bounds = window.L.latLngBounds(this.markers.map((item) => item.marker.getLatLng()));
    this.map.fitBounds(bounds.pad(0.18), { maxZoom: 13 });
  }

  refresh() {
    if (this.ready) setTimeout(() => this.map.invalidateSize(), 60);
  }
}
