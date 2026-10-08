import { Hospital } from "./models.js";
import { loadArray, saveArray, downloadCSV } from "./storage.js";

const KEY = "hospitals";

export class HospitalManager {
  constructor() { this.hospitals = loadArray(KEY).map((h) => new Hospital(h)); }
  save() { saveArray(KEY, this.hospitals); }

  add(data) {
    if (this.getById(data.id)) throw new Error(`Hospital ID already exists: ${data.id}`);
    const h = new Hospital(data);
    this.hospitals.push(h);
    this.save();
    return h;
  }

  getById(id) { return this.hospitals.find((h) => h.id === id) || null; }
  getAll() { return [...this.hospitals]; }

  exportCSV() {
    const headers = ["id","name","lat","lon","totalBeds","availableBeds","emergencyCapacity","status"];
    const rows = this.hospitals.map((h) => [h.id, h.name, h.latitude, h.longitude, h.totalBeds, h.availableBeds, h.emergencyCapacity, h.status]);
    downloadCSV("hospitals.csv", headers, rows);
  }
}
