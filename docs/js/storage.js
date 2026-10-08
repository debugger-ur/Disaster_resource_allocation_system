// localStorage acts as our "persistent file" layer (browser equivalent of the CSVs).
const PREFIX = "drras_";

export function loadArray(key) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.error("Failed to load", key, e);
    return [];
  }
}

export function saveArray(key, arr) {
  localStorage.setItem(PREFIX + key, JSON.stringify(arr));
}

export function clearAll() {
  Object.keys(localStorage)
    .filter((k) => k.startsWith(PREFIX))
    .forEach((k) => localStorage.removeItem(k));
}

// CSV download — satisfies the "file handling" requirement in a browser context.
export function downloadCSV(filename, headers, rows) {
  let csv = headers.join(",") + "\n";
  rows.forEach((row) => { csv += row.join(",") + "\n"; });
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
