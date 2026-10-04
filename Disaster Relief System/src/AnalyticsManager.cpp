#include "AnalyticsManager.h"
#include "Common.h"
#include <iostream>
#include <iomanip>

namespace drras {

AnalyticsManager::AnalyticsManager(DisasterManager &dm, ResourceManager &rm, AllocationManager &am)
    : disasterManager(dm), resourceManager(rm), allocationManager(am) {}

void AnalyticsManager::displayStatistics() const {
    auto all = disasterManager.getAllDisasters();
    auto active = disasterManager.getActiveDisasters();

    int criticalCount = 0;
    long long totalAffected = 0;
    for (const auto &d : active) {
        if (d->getSeverity() == Severity::CRITICAL) ++criticalCount;
        totalAffected += d->getAffectedPeople();
    }

    std::cout << "=========================================\n";
    std::cout << " SYSTEM STATISTICS\n";
    std::cout << "=========================================\n";
    std::cout << "Total Disasters        : " << all.size() << "\n";
    std::cout << "Active Disasters       : " << active.size() << "\n";
    std::cout << "Resolved Disasters     : " << (all.size() - active.size()) << "\n";
    std::cout << "Critical Disasters     : " << criticalCount << "\n";
    std::cout << "People Affected        : " << totalAffected << "\n";
    std::cout << "Available Resources    : " << resourceManager.countAvailable() << "\n";
    std::cout << "Dispatched Resources   : " << resourceManager.countDispatched() << "\n";
    std::cout << "Total Allocations      : " << allocationManager.getHistory().size() << "\n";
    std::cout << "Average Resp. Distance : " << std::fixed << std::setprecision(2)
               << allocationManager.averageAllocationDistance() << " km\n";
    std::cout << "=========================================\n";
}

} // namespace drras