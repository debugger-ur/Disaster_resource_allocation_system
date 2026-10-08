import { Allocation } from "./models.js";
import { loadArray, saveArray, downloadCSV } from "./storage.js";
import { sortByDistance } from "./distanceCalculator.js";

const KEY = "allocations";

export class AllocationManager {
  constructor(resourceManager, disasterManager) {
    this.resourceManager = resourceManager;
    this.disasterManager = disasterManager;
    this.history = loadArray(KEY).map((a) => new Allocation(a));
  }
  save() { saveArray(KEY, this.history); }

  // Core allocation algorithm — STEP1..STEP8 (same logic as C++ AllocationManager).
  allocateForDisaster(disasterId) {
    const disaster = this.disasterManager.getById(disasterId);
    if (!disaster) throw new Error(`Disaster not found: ${disasterId}`);

    const results = [];

    disaster.requiredResources.forEach((category) => {
      const available = this.resourceManager.getAvailableByCategory(category);
      if (!available.length) {
        results.push({ category, candidates: [], selected: null });
        return;
      }
      const ranked = sortByDistance(available, disaster.latitude, disaster.longitude);
      const best = ranked[0];

      this.resourceManager.updateStatus(best.item.id, "DISPATCHED");

      const allocation = new Allocation({
        allocationId: "AL" + (this.history.length + 1),
        disasterId,
        resourceId: best.item.id,
        resourceCategory: category,
        distanceKm: best.distance,
        status: "DISPATCHED",
      });
      this.history.push(allocation);

      results.push({ category, candidates: ranked, selected: best.item, distance: best.distance });
    });

    this.save();
    return results;
  }

  getHistory() { return [...this.history]; }

  averageDistance() {
    if (!this.history.length) return 0;
    return this.history.reduce((s, a) => s + a.distanceKm, 0) / this.history.length;
  }

  exportCSV() {
    const headers = ["allocationId","disasterId","resourceId","resourceCategory","distanceKm","timestamp","status"];
    const rows = this.history.map((a) => [a.allocationId, a.disasterId, a.resourceId, a.resourceCategory, a.distanceKm.toFixed(2), a.timestamp, a.status]);
    downloadCSV("allocations.csv", headers, rows);
  }
}
