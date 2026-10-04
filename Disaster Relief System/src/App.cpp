#include "App.h"
#include "ConsoleUtils.h"
#include "DistanceCalculator.h"
#include "FileManager.h"
#include "Exceptions.h"
#include <iostream>
#include <iomanip>
#include <algorithm>
#include <set>

namespace drras {

App::App()
    : disasterManager(), resourceManager(), hospitalManager(), shelterManager(),
      allocationManager(resourceManager, disasterManager),
      analyticsManager(disasterManager, resourceManager, allocationManager) {
    buildRouteNetwork();
}

void App::showMenu() const {
    std::cout << "\n=========================================\n";
    std::cout << " DISASTER RELIEF RESOURCE ALLOCATION\n";
    std::cout << "             SYSTEM\n";
    std::cout << "=========================================\n";
    std::cout << " 1. Report New Disaster\n";
    std::cout << " 2. View Active Disasters\n";
    std::cout << " 3. Manage Resources\n";
    std::cout << " 4. Find Nearest Resources\n";
    std::cout << " 5. Allocate Resources\n";
    std::cout << " 6. View Hospitals\n";
    std::cout << " 7. View Shelters\n";
    std::cout << " 8. View Allocation History\n";
    std::cout << " 9. View System Statistics\n";
    std::cout << "10. Search Records\n";
    std::cout << "11. Shortest Route (Graph / Dijkstra Demo)\n";
    std::cout << "12. Exit\n";
    std::cout << "=========================================\n";
}

void App::run() {
    bool running = true;
    while (running) {
        showMenu();
        int choice = readInt("Enter choice: ", 1, 12);
        try {
            switch (choice) {
                case 1: reportDisaster(); break;
                case 2: viewActiveDisasters(); break;
                case 3: manageResources(); break;
                case 4: findNearestResources(); break;
                case 5: allocateResources(); break;
                case 6: viewHospitals(); break;
                case 7: viewShelters(); break;
                case 8: viewAllocationHistory(); break;
                case 9: viewStatistics(); break;
                case 10: searchRecords(); break;
                case 11: shortestRouteDemo(); break;
                case 12: running = false; break;
            }
        } catch (const DRRASException &e) {
            std::cout << "\n[Error] " << e.what() << "\n";
        } catch (const std::exception &e) {
            std::cout << "\n[Unexpected Error] " << e.what() << "\n";
        }
    }
    std::cout << "\nSaving data and exiting. Stay safe!\n";
    saveAll();
}

void App::saveAll() const {
    disasterManager.saveToFile();
    resourceManager.saveToFile();
    hospitalManager.saveToFile();
    shelterManager.saveToFile();
    allocationManager.saveToFile();
}

void App::buildRouteNetwork() {
    routeManager.clear();
    for (const auto &d : disasterManager.getAllDisasters())
        routeManager.addLocation(d->getLocationName(), d->getLatitude(), d->getLongitude());
    for (const auto &r : resourceManager.getAll())
        routeManager.addLocation(r->getCurrentLocationName(), r->getLatitude(), r->getLongitude());
    for (const auto &h : hospitalManager.getAll())
        routeManager.addLocation(h->getName(), h->getLatitude(), h->getLongitude());
    for (const auto &s : shelterManager.getAll())
        routeManager.addLocation(s->getName(), s->getLatitude(), s->getLongitude());
    routeManager.buildSimulatedNetwork(3);
}

std::vector<std::string> App::parseResourceSelection(const std::string &input) const {
    static const std::vector<std::string> categories = {"Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply"};
    std::set<std::string> chosen;
    std::stringstream ss(input);
    std::string token;
    while (std::getline(ss, token, ',')) {
        try {
            int idx = std::stoi(token);
            if (idx >= 1 && idx <= static_cast<int>(categories.size())) chosen.insert(categories[idx - 1]);
        } catch (...) { /* ignore bad token */ }
    }
    return {chosen.begin(), chosen.end()};
}

void App::showNearestHospitals(const Disaster &d, int topN) const {
    auto ranked = DistanceCalculator::sortByDistance(hospitalManager.getAll(), d.getLatitude(), d.getLongitude());
    std::cout << "\nNearest Available Hospitals:\n";
    int shown = 0;
    for (const auto &[h, dist] : ranked) {
        if (shown >= topN) break;
        std::cout << "  " << (shown + 1) << ". " << h->getId() << " (" << h->getName() << ") -> "
                  << std::fixed << std::setprecision(1) << dist << " km\n";
        ++shown;
    }
    if (shown == 0) std::cout << "  No hospitals registered.\n";
}

void App::showNearestShelters(const Disaster &d, int topN) const {
    auto ranked = DistanceCalculator::sortByDistance(shelterManager.getAll(), d.getLatitude(), d.getLongitude());
    std::cout << "\nNearest Available Shelters:\n";
    int shown = 0;
    for (const auto &[s, dist] : ranked) {
        if (shown >= topN) break;
        std::cout << "  " << (shown + 1) << ". " << s->getId() << " (" << s->getName() << ") -> "
                  << std::fixed << std::setprecision(1) << dist << " km, Capacity left: "
                  << s->getAvailableCapacity() << "\n";
        ++shown;
    }
    if (shown == 0) std::cout << "  No shelters registered.\n";
}

void App::reportDisaster() {
    std::cout << "\n--- Report New Disaster ---\n";
    std::string id = readLine("Disaster ID: ");
    if (disasterManager.exists(id)) throw DuplicateIDException("Disaster ID already exists: " + id);

    std::cout << "Disaster Type: 1.Flood 2.Earthquake 3.Fire 4.Landslide 5.Industrial Accident 6.Other\n";
    int tChoice = readInt("Choose (1-6): ", 1, 6);
    static const DisasterType types[] = {DisasterType::FLOOD, DisasterType::EARTHQUAKE, DisasterType::FIRE,
                                           DisasterType::LANDSLIDE, DisasterType::INDUSTRIAL_ACCIDENT, DisasterType::OTHER};
    DisasterType type = types[tChoice - 1];

    std::cout << "Severity: 1.CRITICAL 2.HIGH 3.MEDIUM 4.LOW\n";
    int sChoice = readInt("Choose (1-4): ", 1, 4);
    static const Severity sevs[] = {Severity::CRITICAL, Severity::HIGH, Severity::MEDIUM, Severity::LOW};
    Severity severity = sevs[sChoice - 1];

    int affected = readInt("Number of affected people: ", 0, 10000000);

    std::cout << "Required Resource Categories: 1.Ambulance 2.RescueTeam 3.MedicalTeam 4.Equipment 5.Supply\n";
    std::string resInput = readLine("Enter choices (e.g. 1,3,5): ");
    auto requiredResources = parseResourceSelection(resInput);

    std::string locationName = readLine("Location name: ");
    double lat = readDouble("Latitude  (-90 to 90): ", -90.0, 90.0);
    double lon = readDouble("Longitude (-180 to 180): ", -180.0, 180.0);

    auto disaster = disasterManager.addDisaster(id, type, severity, affected, requiredResources,
                                                   locationName, lat, lon);
    FileManager::logMessage("Disaster reported: " + id + " at " + locationName);
    buildRouteNetwork();

    std::cout << "\nDisaster reported successfully.\n";
    disaster->display();

    showNearestHospitals(*disaster, 3);
    showNearestShelters(*disaster, 3);

    char ch = readChoiceChar("\nAllocate resources now? (y/n): ");
    if (ch == 'y' || ch == 'Y') allocationManager.allocateForDisaster(id, true);
}

void App::viewActiveDisasters() {
    auto active = disasterManager.getActiveDisasters();
    if (active.empty()) { std::cout << "\nNo active disasters.\n"; return; }
    std::cout << "\n--- Active Disasters (" << active.size() << ") ---\n";
    for (const auto &d : active) d->display();
}

void App::manageResources() {
    bool back = false;
    while (!back) {
        std::cout << "\n--- Manage Resources ---\n";
        std::cout << "1. Add Resource\n2. View All Resources\n3. Update Resource Status\n"
                   << "4. Search Resource by ID\n5. Back\n";
        int choice = readInt("Choose: ", 1, 5);
        switch (choice) {
            case 1: {
                std::cout << "Category: 1.Ambulance 2.RescueTeam 3.MedicalTeam 4.Equipment 5.Supply\n";
                int cChoice = readInt("Choose (1-5): ", 1, 5);
                static const std::string categories[] = {"Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply"};
                std::string category = categories[cChoice - 1];

                std::string id = readLine("Resource ID: ");
                std::string type = readLine("Type/Description (e.g. ALS, Food, HeavyMachinery): ");
                int quantity = readInt("Quantity/Capacity: ", 0, 1000000);
                double lat = readDouble("Latitude: ", -90.0, 90.0);
                double lon = readDouble("Longitude: ", -180.0, 180.0);
                std::string loc = readLine("Current Location Name: ");
                int priority = readInt("Priority (1=highest .. 5=lowest): ", 1, 5);
                std::string contact = readLine("Contact Info (optional): ");

                resourceManager.addResource(category, id, type, quantity, lat, lon, loc, priority, contact);
                buildRouteNetwork();
                std::cout << "Resource added successfully.\n";
                break;
            }
            case 2: {
                auto all = resourceManager.getAll();
                if (all.empty()) std::cout << "No resources registered.\n";
                for (const auto &r : all) r->display();
                break;
            }
            case 3: {
                std::string id = readLine("Resource ID: ");
                if (!resourceManager.exists(id)) throw RecordNotFoundException("Resource not found: " + id);
                std::cout << "New Status: 1.AVAILABLE 2.DISPATCHED 3.UNAVAILABLE 4.MAINTENANCE\n";
                int sChoice = readInt("Choose (1-4): ", 1, 4);
                static const ResourceStatus statuses[] = {ResourceStatus::AVAILABLE, ResourceStatus::DISPATCHED,
                                                             ResourceStatus::UNAVAILABLE, ResourceStatus::MAINTENANCE};
                resourceManager.updateStatus(id, statuses[sChoice - 1]);
                std::cout << "Status updated.\n";
                break;
            }
            case 4: {
                std::string id = readLine("Resource ID: ");
                auto r = resourceManager.getById(id);
                if (!r) throw RecordNotFoundException("Resource not found: " + id);
                r->display();
                break;
            }
            case 5: back = true; break;
        }
    }
}

void App::findNearestResources() {
    std::cout << "\n--- Find Nearest Resources ---\n";
    std::cout << "1. Use an existing Disaster ID\n2. Enter coordinates manually\n";
    int choice = readInt("Choose: ", 1, 2);

    double lat = 0.0, lon = 0.0;
    std::string refLocationName = "Custom Location";

    if (choice == 1) {
        std::string id = readLine("Disaster ID: ");
        auto d = disasterManager.getById(id);
        if (!d) throw RecordNotFoundException("Disaster not found: " + id);
        lat = d->getLatitude(); lon = d->getLongitude(); refLocationName = d->getLocationName();
    } else {
        lat = readDouble("Latitude: ", -90.0, 90.0);
        lon = readDouble("Longitude: ", -180.0, 180.0);
    }

    std::cout << "Category: 1.Ambulance 2.RescueTeam 3.MedicalTeam 4.Equipment 5.Supply\n";
    int cChoice = readInt("Choose (1-5): ", 1, 5);
    static const std::string categories[] = {"Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply"};
    std::string category = categories[cChoice - 1];

    auto available = resourceManager.getAvailableByCategory(category);
    if (available.empty()) { std::cout << "\nNo available resources of category: " << category << "\n"; return; }

    auto ranked = DistanceCalculator::sortByDistance(available, lat, lon);

    std::cout << "\n-----------------------------------------\n";
    std::cout << "DISTANCE ANALYSIS\n";
    std::cout << "-----------------------------------------\n";
    std::cout << "Reference Location : " << refLocationName << "\n";
    std::cout << "Resource Category  : " << category << "\n";
    std::cout << "-----------------------------------------\n";
    for (const auto &[res, dist] : ranked) {
        std::cout << res->getId() << " (" << res->getCurrentLocationName() << ") -> "
                  << std::fixed << std::setprecision(1) << dist << " km\n";
    }
    std::cout << "-----------------------------------------\n";
}

void App::allocateResources() {
    std::string id = readLine("Disaster ID to allocate resources for: ");
    allocationManager.allocateForDisaster(id, true);
    buildRouteNetwork();
}

void App::viewHospitals() {
    auto all = hospitalManager.getAll();
    if (all.empty()) { std::cout << "\nNo hospitals registered.\n"; return; }
    std::cout << "\n--- Hospitals ---\n";
    for (const auto &h : all) h->display();

    char ch = readChoiceChar("\nFind nearest hospitals to a disaster? (y/n): ");
    if (ch == 'y' || ch == 'Y') {
        std::string id = readLine("Disaster ID: ");
        auto d = disasterManager.getById(id);
        if (!d) throw RecordNotFoundException("Disaster not found: " + id);
        showNearestHospitals(*d, 5);
    }
}

void App::viewShelters() {
    auto all = shelterManager.getAll();
    if (all.empty()) { std::cout << "\nNo shelters registered.\n"; return; }
    std::cout << "\n--- Shelters ---\n";
    for (const auto &s : all) s->display();

    char ch = readChoiceChar("\nFind nearest shelters to a disaster? (y/n): ");
    if (ch == 'y' || ch == 'Y') {
        std::string id = readLine("Disaster ID: ");
        auto d = disasterManager.getById(id);
        if (!d) throw RecordNotFoundException("Disaster not found: " + id);
        showNearestShelters(*d, 5);
    }
}

void App::viewAllocationHistory() {
    const auto &history = allocationManager.getHistory();
    if (history.empty()) { std::cout << "\nNo allocations recorded yet.\n"; return; }
    std::cout << "\n--- Allocation History (" << history.size() << ") ---\n";
    for (const auto &a : history) a.display();
}

void App::viewStatistics() {
    analyticsManager.displayStatistics();
}

void App::searchRecords() {
    std::cout << "\n--- Search Records ---\n";
    std::cout << "1. Disaster by ID\n2. Resource by ID\n3. Resources by Category\n"
               << "4. Search by Location Name\n5. Back\n";
    int choice = readInt("Choose: ", 1, 5);

    switch (choice) {
        case 1: {
            std::string id = readLine("Disaster ID: ");
            auto d = disasterManager.getById(id);
            if (!d) throw RecordNotFoundException("Disaster not found: " + id);
            d->display();
            break;
        }
        case 2: {
            std::string id = readLine("Resource ID: ");
            auto r = resourceManager.getById(id);
            if (!r) throw RecordNotFoundException("Resource not found: " + id);
            r->display();
            break;
        }
        case 3: {
            std::cout << "Category: 1.Ambulance 2.RescueTeam 3.MedicalTeam 4.Equipment 5.Supply\n";
            int cChoice = readInt("Choose (1-5): ", 1, 5);
            static const std::string categories[] = {"Ambulance", "RescueTeam", "MedicalTeam", "Equipment", "Supply"};
            auto results = resourceManager.getByCategory(categories[cChoice - 1]);
            if (results.empty()) std::cout << "No resources found in this category.\n";
            for (const auto &r : results) r->display();
            break;
        }
        case 4: {
            std::string keyword = readLine("Enter location keyword: ");
            bool found = false;
            for (const auto &d : disasterManager.getAllDisasters()) {
                if (d->getLocationName().find(keyword) != std::string::npos) { d->display(); found = true; }
            }
            for (const auto &r : resourceManager.getAll()) {
                if (r->getCurrentLocationName().find(keyword) != std::string::npos) { r->display(); found = true; }
            }
            if (!found) std::cout << "No records found matching: " << keyword << "\n";
            break;
        }
        case 5: break;
    }
}

void App::shortestRouteDemo() {
    buildRouteNetwork();
    auto locations = routeManager.listLocations();
    if (locations.size() < 2) { std::cout << "\nNot enough locations registered to build a route.\n"; return; }

    std::cout << "\nAvailable Locations:\n";
    for (const auto &loc : locations) std::cout << "  - " << loc << "\n";

    std::cout << "\nNOTE: This is a SIMULATED road network built from nearest-neighbour\n"
                 "straight-line distances, not live GPS/road-API data.\n";

    std::string src = readLine("\nSource location: ");
    std::string dst = readLine("Destination location: ");

    auto result = routeManager.shortestPath(src, dst);
    if (!result.found) {
        std::cout << "\nNo path found between '" << src << "' and '" << dst << "' in the simulated network.\n";
        return;
    }

    std::cout << "\n-----------------------------------------\n";
    std::cout << "Source               : " << src << "\n";
    std::cout << "Destination          : " << dst << "\n";
    std::cout << "Shortest Distance    : " << std::fixed << std::setprecision(1) << result.distanceKm << " km\n";
    std::cout << "Estimated Route      : ";
    for (size_t i = 0; i < result.path.size(); ++i) {
        std::cout << result.path[i];
        if (i + 1 < result.path.size()) std::cout << " -> ";
    }
    std::cout << "\n-----------------------------------------\n";
}

} // namespace drras