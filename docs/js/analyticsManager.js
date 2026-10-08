export class AnalyticsManager {
  constructor(disasterManager, resourceManager, allocationManager) {
    this.disasterManager = disasterManager;
    this.resourceManager = resourceManager;
    this.allocationManager = allocationManager;
  }

  getStats() {
    const all = this.disasterManager.getAll();
    const active = this.disasterManager.getActive();
    const critical = active.filter((d) => d.severity === "CRITICAL").length;
    const totalAffected = active.reduce((sum, d) => sum + d.affectedPeople, 0);

    return {
      totalDisasters: all.length,
      activeDisasters: active.length,
      resolvedDisasters: all.length - active.length,
      criticalDisasters: critical,
      peopleAffected: totalAffected,
      availableResources: this.resourceManager.countAvailable(),
      dispatchedResources: this.resourceManager.countDispatched(),
      totalAllocations: this.allocationManager.getHistory().length,
      avgDistance: this.allocationManager.averageDistance(),
    };
  }
}
