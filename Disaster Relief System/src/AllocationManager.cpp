#include "AllocationManager.h"
#include "DistanceCalculator.h"
#include "FileManager.h"
#include "Exceptions.h"
#include "Common.h"
#include <iostream>
#include <iomanip>

namespace drras {

AllocationManager::AllocationManager(ResourceManager &rm, DisasterManager &dm, std::string dataFile)
    : dataFile(std::move(dataFile)), resourceManager(rm), disasterManager(dm) {
    loadFromFile();
}

void AllocationManager::loadFromFile() {
    const std::string header = "allocationId,disasterId,resourceId,resourceCategory,distanceKm,timestamp,status";
    FileManager::ensureFile(dataFile, header);
    auto rows = FileManager::readCSV(dataFile);
    for (const auto &row : rows) {
        if (row.size() < 7) continue;
        try {
            Allocation a;
            a.allocationId = row[0]; a.disasterId = row[1]; a.resourceId = row[2];
            a.resourceCategory = row[3]; a.distanceKm = std::stod(row[4]);
            a.timestamp = row[5]; a.status = row[6];
            history.push_back(a);
        } catch (const std::exception &) { continue; }
    }
}

void AllocationManager::saveToFile() const {
    std::vector<std::vector<std::string>> rows;
    for (const auto &a : history) {
        rows.push_back({a.allocationId, a.disasterId, a.resourceId, a.resourceCategory,
                         std::to_string(a.distanceKm), a.timestamp, a.status});
    }
    FileManager::writeCSVAll(dataFile, "allocationId,disasterId,resourceId,resourceCategory,distanceKm,timestamp,status", rows);
}

// ---------------------------------------------------------------------
// ALLOCATION ALGORITHM (STEP 1 - STEP 8 from the specification)
// STEP1: read disaster severity & requirements
// STEP2: find matching AVAILABLE resources
// STEP3: auto-calculate distance (Haversine) for every candidate
// STEP4-5: sort by distance (nearest-first = highest suitability score here,
//           since all candidates are already filtered by category+availability
//           and the disaster's severity already determined queue priority)
// STEP6: mark selected resource DISPATCHED
// STEP7: record allocation in history
// STEP8: display result
// Complexity per required-category: O(n log n) for sorting n candidates.
// ---------------------------------------------------------------------
std::vector<Allocation> AllocationManager::allocateForDisaster(const std::string &disasterId, bool verbose) {
    auto disaster = disasterManager.getById(disasterId);
    if (!disaster) throw RecordNotFoundException("Disaster not found: " + disasterId);

    std::vector<Allocation> allocatedThisRun;

    if (verbose) {
        std::cout << "-----------------------------------------\n";
        std::cout << "RESOURCE ALLOCATION\n";
        std::cout << "-----------------------------------------\n";
        std::cout << "Disaster  : " << disasterId << "\n";
        std::cout << "Severity  : " << severityToString(disaster->getSeverity()) << "\n";
    }

    for (const auto &category : disaster->getRequiredResources()) {
        auto available = resourceManager.getAvailableByCategory(category);

        if (available.empty()) {
            if (verbose) std::cout << "\nNo available resources of type: " << category << "\n";
            continue;
        }

        auto ranked = DistanceCalculator::sortByDistance(available, disaster->getLatitude(), disaster->getLongitude());

        if (verbose) {
            std::cout << "\nAvailable " << category << "s:\n";
            for (const auto &[res, dist] : ranked) {
                std::cout << "  " << res->getId() << " -> " << std::fixed << std::setprecision(1)
                          << dist << " km\n";
            }
        }

        // Nearest available candidate -> already filtered on availability,
        // so if it later becomes unavailable mid-loop the next entry wins.
        auto &best = ranked.front();
        resourceManager.updateStatus(best.first->getId(), ResourceStatus::DISPATCHED);

        Allocation alloc;
        alloc.allocationId = "AL" + std::to_string(history.size() + 1);
        alloc.disasterId = disasterId;
        alloc.resourceId = best.first->getId();
        alloc.resourceCategory = category;
        alloc.distanceKm = best.second;
        alloc.timestamp = currentTimestamp();
        alloc.status = "DISPATCHED";

        history.push_back(alloc);
        allocatedThisRun.push_back(alloc);

        if (verbose) {
            std::cout << "\nSelected Resource : " << alloc.resourceId << "\n";
            std::cout << "Distance          : " << std::fixed << std::setprecision(1)
                       << alloc.distanceKm << " km\n";
            std::cout << "Status            : DISPATCHED\n";
        }

        FileManager::logMessage("Allocated " + alloc.resourceId + " to disaster " + disasterId +
                                  " (" + std::to_string(alloc.distanceKm) + " km)");
    }

    if (verbose) std::cout << "-----------------------------------------\n";
    saveToFile();
    return allocatedThisRun;
}

double AllocationManager::averageAllocationDistance() const {
    if (history.empty()) return 0.0;
    double sum = 0.0;
    for (const auto &a : history) sum += a.distanceKm;
    return sum / static_cast<double>(history.size());
}

} // namespace drras