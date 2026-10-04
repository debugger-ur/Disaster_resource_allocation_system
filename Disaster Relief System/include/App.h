#pragma once
#include "DisasterManager.h"
#include "ResourceManager.h"
#include "HospitalManager.h"
#include "ShelterManager.h"
#include "AllocationManager.h"
#include "AnalyticsManager.h"
#include "RouteManager.h"
#include "Disaster.h"
#include <vector>
#include <string>

namespace drras {

// Orchestrates the whole console application. Pure UI glue — all real
// logic lives in the Manager classes (separation of UI vs business logic).
class App {
    DisasterManager disasterManager;
    ResourceManager resourceManager;
    HospitalManager hospitalManager;
    ShelterManager shelterManager;
    AllocationManager allocationManager;
    AnalyticsManager analyticsManager;
    RouteManager routeManager;

public:
    App();
    void run();

private:
    void showMenu() const;
    void reportDisaster();
    void viewActiveDisasters();
    void manageResources();
    void findNearestResources();
    void allocateResources();
    void viewHospitals();
    void viewShelters();
    void viewAllocationHistory();
    void viewStatistics();
    void searchRecords();
    void shortestRouteDemo();

    void buildRouteNetwork();
    void saveAll() const;

    void showNearestHospitals(const Disaster &d, int topN) const;
    void showNearestShelters(const Disaster &d, int topN) const;
    std::vector<std::string> parseResourceSelection(const std::string &input) const;
};

} // namespace drras