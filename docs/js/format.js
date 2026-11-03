/** Tiny DOM + formatting helpers shared by both dashboards. */

export const qs = (selector, root = document) => root.querySelector(selector);
export const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function attr(value) {
  return esc(value).replaceAll("`", "&#96;");
}

export function icon(name, size = 16, className = "") {
  return `<svg width="${size}" height="${size}" class="${className}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

export function debounce(fn, delay = 280) {
  let handle;
  return (...args) => {
    clearTimeout(handle);
    handle = setTimeout(() => fn(...args), delay);
  };
}

export function fmtDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function fmtTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
}

export function fmtRelative(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  const future = seconds < 0;
  const abs = Math.abs(seconds);
  const units = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.34, "week"],
    [12, "month"],
    [Infinity, "year"],
  ];
  let valueNum = abs;
  let unit = "second";
  for (const [size, name] of units) {
    if (valueNum < size) {
      unit = name;
      break;
    }
    valueNum /= size;
    unit = name;
  }
  const rounded = Math.max(1, Math.round(valueNum));
  try {
    return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
      future ? rounded : -rounded,
      unit,
    );
  } catch {
    return `${rounded} ${unit}${rounded === 1 ? "" : "s"} ${future ? "from now" : "ago"}`;
  }
}

export function fmtNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : "—";
}

export function fmtDistance(km) {
  const number = Number(km);
  if (!Number.isFinite(number)) return "—";
  if (number < 1) return `${Math.round(number * 1000)} m`;
  return `${number.toFixed(number < 10 ? 1 : 0)} km`;
}

export function fmtDuration(minutes) {
  const number = Number(minutes);
  if (!Number.isFinite(number) || number <= 0) return "—";
  if (number < 60) return `${Math.round(number)} min`;
  const hours = Math.floor(number / 60);
  const rest = Math.round(number % 60);
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export function fmtBytes(bytes) {
  const number = Number(bytes);
  if (!Number.isFinite(number)) return "—";
  if (number < 1024) return `${number} B`;
  if (number < 1024 * 1024) return `${(number / 1024).toFixed(0)} KB`;
  return `${(number / (1024 * 1024)).toFixed(1)} MB`;
}

export function titleCase(value) {
  const text = String(value ?? "").replaceAll("_", " ").trim().toLowerCase();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

export const STATUS_META = {
  submitted: { label: "Submitted", tone: "", description: "Received and queued for verification." },
  under_verification: { label: "Under verification", tone: "info", description: "A coordinator is checking the details." },
  possible_duplicate: { label: "Possible duplicate", tone: "purple", description: "A similar report exists; a person decides whether to merge." },
  awaiting_approval: { label: "Awaiting approval", tone: "warn", description: "In the approval queue for a coordinator." },
  approved: { label: "Approved", tone: "ok", description: "Eligible for resource allocation." },
  rejected: { label: "Rejected", tone: "danger", description: "Closed by a person with a recorded reason." },
  resources_assigned: { label: "Resources assigned", tone: "info", description: "Stock committed from a help centre." },
  in_progress: { label: "In progress", tone: "info", description: "Dispatch and delivery under way." },
  resolved: { label: "Resolved", tone: "ok", description: "Response complete." },
};

export const STATUS_ORDER = [
  "submitted",
  "under_verification",
  "possible_duplicate",
  "awaiting_approval",
  "approved",
  "resources_assigned",
  "in_progress",
  "resolved",
];

export const TERMINAL_STATUSES = new Set(["rejected", "resolved"]);

export function statusBadge(status, { large = false } = {}) {
  const meta = STATUS_META[status] || { label: titleCase(status) || "Unknown" };
  const size = large ? " badge--lg" : "";
  return `<span class="badge status${size}" data-status="${attr(status)}">${esc(meta.label)}</span>`;
}

export function riskBadge(level, score) {
  const label = { low: "Low risk", medium: "Medium risk", high: "High risk" }[level] || "Unknown risk";
  const value = Number.isFinite(Number(score)) ? ` · ${score}` : "";
  return `<span class="badge risk" data-risk="${attr(level)}">${esc(label)}${value}</span>`;
}

export function severityBadge(severity) {
  const label = titleCase(severity);
  return `<span class="badge severity" data-severity="${attr(severity)}">${esc(label)}</span>`;
}

export function availabilityBadge(status) {
  return `<span class="badge avail" data-availability="${attr(status)}">${esc(titleCase(status))}</span>`;
}

export function resourceLabel(category) {
  return {
    Ambulance: "Ambulance",
    RescueTeam: "Rescue team",
    MedicalTeam: "Medical team",
    Equipment: "Equipment",
    Supply: "Food & supply kits",
  }[category] || titleCase(category);
}

export const RESOURCE_ORDER = ["RescueTeam", "MedicalTeam", "Ambulance", "Equipment", "Supply"];

export function itemsSummary(items) {
  const entries = Object.entries(items || {}).filter(([, value]) => Number(value) > 0);
  if (!entries.length) return "—";
  return entries
    .sort(([a], [b]) => RESOURCE_ORDER.indexOf(a) - RESOURCE_ORDER.indexOf(b))
    .map(([category, amount]) => `${amount} ${resourceLabel(category)}`)
    .join(" · ");
}

export function stockSummary(stock) {
  const entries = Object.entries(stock || {}).filter(([, value]) => Number(value) > 0);
  if (!entries.length) return "No stock recorded";
  return entries
    .sort(([a], [b]) => RESOURCE_ORDER.indexOf(a) - RESOURCE_ORDER.indexOf(b))
    .slice(0, 4)
    .map(([category, amount]) => `${resourceLabel(category)} ${amount}`)
    .join(" · ");
}

export async function copyText(value) {
  const text = String(value);
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    area.remove();
    return ok;
  }
}

export function escapeAttr(value) {
  return String(value ?? "").replaceAll('"', "&quot;");
}

export function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}
