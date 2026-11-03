/**
 * Leaflet wrapper used by the public site and the command centre.
 * Markers use distinct shapes/colours per help-centre category, and every
 * route drawn here is real OSRM geometry (estimates are never drawn as a line).
 */

export const CATEGORY_META = {
  incident: { label: "Active incident", color: "#b42318", glyph: "alert" },
  hospital: { label: "Hospital", color: "#175cd3", glyph: "cross" },
  relief_camp: { label: "Relief camp", color: "#067647", glyph: "tent" },
  food_water: { label: "Food & water", color: "#b54708", glyph: "droplet" },
  rescue_team: { label: "Rescue team", color: "#6938ef", glyph: "rescue" },
  warehouse: { label: "Warehouse", color: "#475467", glyph: "box" },
  shelter: { label: "Shelter", color: "#0e7090", glyph: "home" },
  medical_camp: { label: "Medical camp", color: "#c11574", glyph: "pulse" },
  other: { label: "Other help centre", color: "#667085", glyph: "dot" },
  user: { label: "Selected location", color: "#0b1f33", glyph: "pin" },
};

const GLYPHS = {
  alert: '<path d="M12 3 2.4 20h19.2L12 3Z"/><path d="M12 9v5M12 17h.01"/>',
  cross: '<path d="M9.5 4h5v5.5H20v5h-5.5V20h-5v-5.5H4v-5h5.5Z"/>',
  tent: '<path d="M12 4 2.8 20h18.4L12 4Z"/><path d="M12 11v9"/>',
  droplet: '<path d="M12 3.2S6.3 9.6 6.3 13a5.7 5.7 0 0 0 11.4 0c0-3.4-5.7-9.8-5.7-9.8Z"/>',
  rescue: '<circle cx="12" cy="12" r="7.4"/><path d="M12 4.6v14.8M4.6 12h14.8"/>',
  box: '<path d="m3 8 9-4 9 4-9 4-9-4Z"/><path d="M3 8v8l9 4 9-4V8M12 12v8"/>',
  home: '<path d="m3.5 10.4 8.5-6.6 8.5 6.6V20h-6v-6h-5v6h-6Z"/>',
  pulse: '<path d="M2.5 12h4l2.2-6 4 12 2.3-6h6.5"/>',
  dot: '<circle cx="12" cy="12" r="4.2"/>',
  pin: '<path d="M19 10.4c0 5.4-7 10.6-7 10.6s-7-5.2-7-10.6a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.6"/>',
};

export function markerHtml(category, { selected = false, incident = false } = {}) {
  const meta = CATEGORY_META[category] || CATEGORY_META.other;
  const glyph = GLYPHS[meta.glyph] || GLYPHS.dot;
  const classes = [
    "marker-pin",
    incident || category === "incident" ? "marker-pin--incident" : "",
    selected ? "marker-pin--selected" : "",
    category === "user" ? "marker-pin--user" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return `<div class="${classes}" style="--marker-colour:${meta.color};color:${meta.color}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${glyph}</svg>
  </div>`;
}

function divIcon(category, { selected = false } = {}) {
  const incident = category === "incident";
  const size = incident ? 34 : 30;
  return window.L.divIcon({
    html: markerHtml(category, { selected, incident }),
    className: "map-marker",
    iconSize: [size, size],
    iconAnchor: [size / 2, size],
    popupAnchor: [0, -size + 4],
  });
}

export class DrrasMap {
  constructor(element, options = {}) {
    this.element = element;
    this.options = {
      center: [30.3165, 78.0322],
      zoom: 11,
      interactive: true,
      zoomControl: true,
      ...options,
    };
    this.markers = new Map();
    this.selectedKey = null;
    this.clickHandler = null;
    this.routeLine = null;
    this.radiusCircle = null;
    this.ready = false;

    if (!window.L) {
      element.innerHTML =
        '<div class="empty" style="padding:30px"><h3>Map library unavailable</h3><p>The bundled Leaflet files could not be loaded. The list of help centres below is still complete and usable.</p></div>';
      return;
    }

    this.L = window.L;
    this.map = this.L.map(element, {
      zoomControl: this.options.zoomControl,
      attributionControl: true,
      scrollWheelZoom: this.options.interactive,
      dragging: this.options.interactive,
      doubleClickZoom: this.options.interactive,
    });
    this.map.setView(this.options.center, this.options.zoom);
    this.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);

    this.routeLayer = this.L.layerGroup().addTo(this.map);
    this.centreLayer = this.L.layerGroup().addTo(this.map);
    this.incidentLayer = this.L.layerGroup().addTo(this.map);
    this.pickLayer = this.L.layerGroup().addTo(this.map);

    this.map.on("click", (event) => {
      if (typeof this.clickHandler === "function") this.clickHandler(event.latlng, this);
    });

    this.ready = true;
    // Layout can settle after instantiation (tabs, drawers, grid).
    setTimeout(() => this.map.invalidateSize(), 150);
    setTimeout(() => this.map.invalidateSize(), 600);
  }

  invalidate() {
    if (this.ready) this.map.invalidateSize();
  }

  onMapClick(handler) {
    this.clickHandler = handler;
  }

  clearGroup(group) {
    group.clearLayers();
  }

  _mapKey(prefix, id) {
    return `${prefix}:${id}`;
  }

  _addMarker(group, key, item, category, { popup, onClick, selected = false } = {}) {
    const marker = this.L.marker([item.latitude, item.longitude], {
      icon: divIcon(category, { selected }),
      keyboard: true,
      title: item.name || item.label || item.locationName || category,
      riseOnHover: true,
    });
    if (popup) marker.bindPopup(popup, { closeButton: false, offset: [0, -2] });
    marker.on("click", (event) => {
      if (event.originalEvent) this.L.DomEvent.stopPropagation(event);
      if (typeof onClick === "function") onClick(item);
    });
    marker.addTo(group);
    this.markers.set(key, marker);
    return marker;
  }

  setCentres(centres, { onClick, selectedId = null, popup = true } = {}) {
    if (!this.ready) return;
    this.centreLayer.clearLayers();
    Array.from(this.markers.keys())
      .filter((key) => key.startsWith("centre:"))
      .forEach((key) => this.markers.delete(key));
    (centres || []).forEach((centre) => {
      const category = CATEGORY_META[centre.category] ? centre.category : "other";
      const key = this._mapKey("centre", centre.id);
      const selected = selectedId === centre.id;
      this._addMarker(this.centreLayer, key, centre, category, {
        onClick,
        selected,
        popup: popup
          ? `<strong>${escapeText(centre.name)}</strong><br>${escapeText(CATEGORY_META[category].label)}`
            + (centre.distanceKm !== undefined ? `<br>${Number(centre.distanceKm).toFixed(1)} km away` : "")
          : null,
      });
      if (selected) this.selectedKey = key;
    });
  }

  setIncidents(incidents, { onClick, popup = true } = {}) {
    if (!this.ready) return;
    this.incidentLayer.clearLayers();
    Array.from(this.markers.keys())
      .filter((key) => key.startsWith("incident:"))
      .forEach((key) => this.markers.delete(key));
    (incidents || []).forEach((incident) => {
      const key = this._mapKey("incident", incident.id);
      this._addMarker(this.incidentLayer, key, { ...incident, name: incident.locationName }, "incident", {
        onClick,
        popup: popup
          ? `<strong>${escapeText(incident.locationName || "Incident")}</strong><br>`
            + `${escapeText(String(incident.type || "").replaceAll("_", " "))}`
            + (incident.workflowLabel ? ` · ${escapeText(incident.workflowLabel)}` : "")
          : null,
      });
    });
  }

  selectCentre(id) {
    if (!this.ready) return;
    this.markers.forEach((marker, key) => {
      if (!key.startsWith("centre:")) return;
      const element = marker.getElement()?.querySelector(".marker-pin");
      if (!element) return;
      const isSelected = key === `centre:${id}`;
      element.classList.toggle("marker-pin--selected", isSelected);
    });
  }

  addRoute(points, { fit = true } = {}) {
    if (!this.ready) return;
    this.clearRoute();
    if (!Array.isArray(points) || points.length < 2) return;
    this.routeLine = this.L.polyline(points, {
      color: "#0b1f33",
      weight: 4,
      opacity: 0.85,
      lineCap: "round",
    }).addTo(this.routeLayer);
    if (fit) {
      const bounds = this.L.latLngBounds(points.map(([lat, lon]) => [lat, lon]));
      this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    }
  }

  clearRoute() {
    if (!this.ready) return;
    this.routeLayer.clearLayers();
    this.routeLine = null;
  }

  setRadius(latitude, longitude, km, color = "#0b1f33") {
    if (!this.ready) return;
    if (this.radiusCircle) {
      this.map.removeLayer(this.radiusCircle);
      this.radiusCircle = null;
    }
    if (!km) return;
    this.radiusCircle = this.L.circle([latitude, longitude], {
      radius: km * 1000,
      color,
      weight: 1,
      opacity: 0.35,
      fillColor: color,
      fillOpacity: 0.04,
      interactive: false,
    }).addTo(this.map);
  }

  setOrigin(latitude, longitude, { pan = true, zoom = null, label = "Selected location" } = {}) {
    if (!this.ready) return;
    this.pickLayer.clearLayers();
    this.originMarker = this.L.marker([latitude, longitude], {
      icon: divIcon("user"),
      keyboard: false,
      zIndexOffset: 600,
      title: label,
    }).addTo(this.pickLayer);
    if (pan) {
      this.map.setView([latitude, longitude], zoom ?? Math.max(this.map.getZoom(), 13));
    }
    return this.originMarker;
  }

  setPickerMarker(latitude, longitude, { onMove = null, draggable = true } = {}) {
    if (!this.ready) return null;
    this.pickLayer.clearLayers();
    const marker = this.L.marker([latitude, longitude], {
      icon: divIcon("incident"),
      draggable,
      autoPan: true,
      zIndexOffset: 700,
      keyboard: true,
      title: "Disaster location pin",
    }).addTo(this.pickLayer);
    marker.on("dragend", () => {
      const position = marker.getLatLng();
      if (typeof onMove === "function") onMove(position.lat, position.lng);
    });
    this.pickerMarker = marker;
    return marker;
  }

  clearPickerMarker() {
    if (!this.ready) return;
    this.pickLayer.clearLayers();
    this.pickerMarker = null;
  }

  movePicker(latitude, longitude) {
    if (!this.ready) return;
    if (this.pickerMarker) {
      this.pickerMarker.setLatLng([latitude, longitude]);
    } else {
      this.setPickerMarker(latitude, longitude);
    }
  }

  focus(latitude, longitude, zoom = 14) {
    if (!this.ready) return;
    this.map.setView([latitude, longitude], zoom);
  }

  fit(points, { maxZoom = 15, padding = [36, 36] } = {}) {
    if (!this.ready || !points?.length) return;
    const bounds = this.L.latLngBounds(points.map(([lat, lon]) => [lat, lon]));
    this.map.fitBounds(bounds, { padding, maxZoom });
  }
}

function escapeText(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
