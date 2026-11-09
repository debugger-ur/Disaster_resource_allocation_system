const TOKEN_KEY = "drras_token";
const CSRF_KEY = "drras_csrf";

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export function setSession(data) {
  if (data && data.sessionToken) sessionStorage.setItem(TOKEN_KEY, data.sessionToken);
  if (data && data.csrfToken) sessionStorage.setItem(CSRF_KEY, data.csrfToken);
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(CSRF_KEY);
}

export async function api(path, { method = "GET", body, headers = {} } = {}) {
  const options = {
    method,
    credentials: "same-origin",
    headers: { ...headers },
  };
  const token = sessionStorage.getItem(TOKEN_KEY);
  const csrf = sessionStorage.getItem(CSRF_KEY);
  if (token) options.headers.Authorization = `Bearer ${token}`;
  if (csrf && method !== "GET") options.headers["X-CSRF-Token"] = csrf;
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: "Unexpected server response." }; }
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

export async function requireAdminSession() {
  const data = await api("/api/admin/session");
  setSession(data);
  return data;
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

export function fmtDate(value, withTime = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-IN", withTime
    ? { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "short", year: "numeric" });
}

export function timeAgo(value) {
  const date = new Date(value);
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} day(s) ago`;
}

export function statusBadge(status, label) {
  return `<span class="badge status-${escapeHtml(status)}">${escapeHtml(label || status.replace(/_/g, " "))}</span>`;
}

export function resourceSummary(resources) {
  const labels = {
    Food: "Food", Water: "Water", Medicine: "Medicine", RescueTeam: "Rescue team",
    MedicalTeam: "Medical team", Shelter: "Shelter", Other: "Other",
  };
  return Object.entries(resources || {})
    .map(([name, amount]) => `${escapeHtml(labels[name] || name)} × ${Number(amount)}`)
    .join(" · ");
}

export function debounce(callback, wait = 350) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => callback(...args), wait);
  };
}

let toastTimer;
export function toast(message, kind = "info") {
  const element = $("#toast");
  if (!element) return;
  element.textContent = message;
  element.style.background = kind === "error" ? "#991b1b" : kind === "success" ? "#166534" : "#102a43";
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.hidden = true; }, 3600);
}
