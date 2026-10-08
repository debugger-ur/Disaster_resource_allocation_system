import { Disaster } from "./models.js";
import { loadArray, saveArray, downloadCSV } from "./storage.js";

const KEY = "disasters";

export class DisasterManager {
  constructor() {
    this.disasters = loadArray(KEY).map((d) => new Disaster(d));
  }
  save() { saveArray(KEY, this.disasters); }

  add(data) {
    if (this.getById(data.id)) throw new Error(`Disaster ID already exists: ${data.id}`);
    const disaster = new Disaster(data);
    this.disasters.push(disaster);
    this.save();
    return disaster;
  }

  getById(id) { return this.disasters.find((d) => d.id === id) || null; }
  getAll() { return [...this.disasters]; }
  getActive() { return this.disasters.filter((d) => d.status === "ACTIVE"); }

  resolve(id) {
    const d = this.getById(id);
    if (!d) throw new Error(`Disaster not found: ${id}`);
    d.status = "RESOLVED";
    this.save();
  }

  // Priority-queue-style ordering: CRITICAL always before HIGH/MEDIUM/LOW.
  getByPriorityOrder() {
    return this.getActive().sort((a, b) => b.priorityScore - a.priorityScore);
  }

  exportCSV() {
    const headers = ["id","type","severity","affected","requiredResources","locationName","lat","lon","timestamp","status"];
    const rows = this.disasters.map((d) => [
      d.id, d.type, d.severity, d.affectedPeople, d.requiredResources.join(";"),
      d.locationName, d.latitude, d.longitude, d.timestamp, d.status,
    ]);
    downloadCSV("disasters.csv", headers, rows);
  }
}
