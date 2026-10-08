import { Resource } from "./models.js";
import { loadArray, saveArray, downloadCSV } from "./storage.js";
import { sortByDistance } from "./distanceCalculator.js";

const KEY = "resources";

export class ResourceManager {
  constructor() {
    this.resources = loadArray(KEY).map((r) => new Resource(r));
  }
  save() { saveArray(KEY, this.resources); }

  add(data) {
    if (this.getById(data.id)) throw new Error(`Resource ID already exists: ${data.id}`);
    const resource = new Resource(data);
    this.resources.push(resource);
    this.save();
    return resource;
  }

  getById(id) { return this.resources.find((r) => r.id === id) || null; }
  getAll() { return [...this.resources]; }
  getByCategory(category) { return this.resources.filter((r) => r.category === category); }
  getAvailableByCategory(category) {
    return this.resources.filter((r) => r.category === category && r.status === "AVAILABLE");
  }

  updateStatus(id, status) {
    const r = this.getById(id);
    if (!r) throw new Error(`Resource not found: ${id}`);
    r.status = status;
    this.save();
  }

  countAvailable() { return this.resources.filter((r) => r.status === "AVAILABLE").length; }
  countDispatched() { return this.resources.filter((r) => r.status === "DISPATCHED").length; }

  nearestAvailable(category, lat, lon) {
    return sortByDistance(this.getAvailableByCategory(category), lat, lon);
  }

  exportCSV() {
    const headers = ["id","category","type","quantity","status","lat","lon","locationName","priority","contact"];
    const rows = this.resources.map((r) => [
      r.id, r.category, r.type, r.quantity, r.status, r.latitude, r.longitude, r.locationName, r.priority, r.contact,
    ]);
    downloadCSV("resources.csv", headers, rows);
  }
}
