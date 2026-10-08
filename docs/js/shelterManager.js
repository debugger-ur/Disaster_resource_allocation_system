import { Shelter } from "./models.js";
import { loadArray, saveArray, downloadCSV } from "./storage.js";

const KEY = "shelters";

export class ShelterManager {
  constructor() { this.shelters = loadArray(KEY).map((s) => new Shelter(s)); }
  save() { saveArray(KEY, this.shelters); }

  add(data) {
    if (this.getById(data.id)) throw new Error(`Shelter ID already exists: ${data.id}`);
    const s = new Shelter(data);
    this.shelters.push(s);
    this.save();
    return s;
  }

  getById(id) { return this.shelters.find((s) => s.id === id) || null; }
  getAll() { return [...this.shelters]; }

  exportCSV() {
    const headers = ["id","name","lat","lon","capacity","occupied"];
    const rows = this.shelters.map((s) => [s.id, s.name, s.latitude, s.longitude, s.capacity, s.occupied]);
    downloadCSV("shelters.csv", headers, rows);
  }
}
