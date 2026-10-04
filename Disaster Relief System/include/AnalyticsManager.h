#pragma once
#include "DisasterManager.h"
#include "ResourceManager.h"
#include "AllocationManager.h"

namespace drras {

class AnalyticsManager {
    DisasterManager &disasterManager;
    ResourceManager &resourceManager;
    AllocationManager &allocationManager;

public:
    AnalyticsManager(DisasterManager &dm, ResourceManager &rm, AllocationManager &am);
    void displayStatistics() const;
};

} // namespace drras