#pragma once
#include <vector>
#include <string>
#include "Allocation.h"
#include "DisasterManager.h"
#include "ResourceManager.h"

namespace drras {

// The heart of STEP-by-STEP allocation algorithm described in the spec.
class AllocationManager {
    std::vector<Allocation> history;
    std::string dataFile;
    ResourceManager &resourceManager;
    DisasterManager &disasterManager;

public:
    AllocationManager(ResourceManager &rm, DisasterManager &dm,
                        std::string dataFile = "data/allocations.csv");

    void loadFromFile();
    void saveToFile() const;

    // Runs STEP1..STEP8 of the allocation algorithm for one disaster.
    std::vector<Allocation> allocateForDisaster(const std::string &disasterId, bool verbose = true);

    const std::vector<Allocation>& getHistory() const { return history; }
    double averageAllocationDistance() const;
};

} // namespace drras