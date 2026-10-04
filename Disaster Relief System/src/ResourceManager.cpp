#include "ResourceManager.h"
#include "FileManager.h"
#include "Exceptions.h"

namespace drras {

ResourceManager::ResourceManager(std::string dataFile) : dataFile(std::move(dataFile)) {
    loadFromFile();
}

std::shared_ptr<Resource> ResourceManager::createResource(
    const std::string &category, const std::string &id, const std::string &type,
    int quantity, ResourceStatus status, double lat, double lon,
    const std::string &locationName, int priority, const std::string &contact) {

    if (category == "Ambulance")
        return std::make_shared<Ambulance>(id, type, quantity, status, lat, lon, locationName, priority, contact);
    if (category == "RescueTeam")
        return std::make_shared<RescueTeam>(id, type, quantity, status, lat, lon, locationName, priority, contact);
    if (category == "MedicalTeam")
        return std::make_shared<MedicalTeam>(id, type, quantity, status, lat, lon, locationName, priority, contact);
    if (category == "Equipment")
        return std::make_shared<Equipment>(id, type, quantity, status, lat, lon, locationName, priority, contact);
    if (category == "Supply")
        return std::make_shared<Supply>(id, type, quantity, status, lat, lon, locationName, priority, contact);

    throw InvalidInputException("Unknown resource category: " + category);
}

void ResourceManager::loadFromFile() {
    const std::string header = "id,category,type,quantity,status,lat,lon,locationName,priority,contact";
    FileManager::ensureFile(dataFile, header);
    auto rows = FileManager::readCSV(dataFile);

    for (const auto &row : rows) {
        if (row.size() < 10) continue;
        try {
            auto res = createResource(row[1], row[0], row[2], std::stoi(row[3]),
                                        stringToResourceStatus(row[4]), std::stod(row[5]),
                                        std::stod(row[6]), row[7], std::stoi(row[8]), row[9]);
            resources.push_back(res);
            indexById[res->getId()] = res;
        } catch (const std::exception &) {
            continue;
        }
    }
}

void ResourceManager::saveToFile() const {
    std::vector<std::vector<std::string>> rows;
    for (const auto &r : resources) {
        rows.push_back({
            r->getId(), r->getCategory(), r->getType(), std::to_string(r->getQuantity()),
            resourceStatusToString(r->getStatus()), std::to_string(r->getLatitude()),
            std::to_string(r->getLongitude()), r->getCurrentLocationName(),
            std::to_string(r->getPriority()), r->getContactInfo()
        });
    }
    FileManager::writeCSVAll(dataFile,
        "id,category,type,quantity,status,lat,lon,locationName,priority,contact", rows);
}

std::shared_ptr<Resource> ResourceManager::addResource(
    const std::string &category, const std::string &id, const std::string &type,
    int quantity, double lat, double lon, const std::string &locationName,
    int priority, const std::string &contact) {

    if (exists(id)) throw DuplicateIDException("Resource ID already exists: " + id);

    auto res = createResource(category, id, type, quantity, ResourceStatus::AVAILABLE,
                                lat, lon, locationName, priority, contact);
    resources.push_back(res);
    indexById[id] = res;
    saveToFile();
    return res;
}

std::shared_ptr<Resource> ResourceManager::getById(const std::string &id) const {
    auto it = indexById.find(id);
    return it == indexById.end() ? nullptr : it->second;
}

std::vector<std::shared_ptr<Resource>> ResourceManager::getAll() const {
    return resources;
}

std::vector<std::shared_ptr<Resource>> ResourceManager::getByCategory(const std::string &category) const {
    std::vector<std::shared_ptr<Resource>> result;
    for (const auto &r : resources) if (r->getCategory() == category) result.push_back(r);
    return result;
}

std::vector<std::shared_ptr<Resource>> ResourceManager::getAvailableByCategory(const std::string &category) const {
    std::vector<std::shared_ptr<Resource>> result;
    for (const auto &r : resources) if (r->getCategory() == category && r->isAvailable()) result.push_back(r);
    return result;
}

bool ResourceManager::updateStatus(const std::string &id, ResourceStatus status) {
    auto it = indexById.find(id);
    if (it == indexById.end()) return false;
    it->second->setStatus(status);
    saveToFile();
    return true;
}

bool ResourceManager::exists(const std::string &id) const {
    return indexById.find(id) != indexById.end();
}

int ResourceManager::countAvailable() const {
    int c = 0;
    for (const auto &r : resources) if (r->isAvailable()) ++c;
    return c;
}

int ResourceManager::countDispatched() const {
    int c = 0;
    for (const auto &r : resources) if (r->getStatus() == ResourceStatus::DISPATCHED) ++c;
    return c;
}

} // namespace drras