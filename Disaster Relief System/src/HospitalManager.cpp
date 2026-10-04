#include "HospitalManager.h"
#include "FileManager.h"
#include "Exceptions.h"

namespace drras {

HospitalManager::HospitalManager(std::string dataFile) : dataFile(std::move(dataFile)) {
    loadFromFile();
}

void HospitalManager::loadFromFile() {
    const std::string header = "id,name,lat,lon,totalBeds,availableBeds,emergencyCapacity,status";
    FileManager::ensureFile(dataFile, header);
    auto rows = FileManager::readCSV(dataFile);

    for (const auto &row : rows) {
        if (row.size() < 8) continue;
        try {
            auto h = std::make_shared<Hospital>(row[0], row[1], std::stod(row[2]), std::stod(row[3]),
                                                  std::stoi(row[4]), std::stoi(row[5]), std::stoi(row[6]), row[7]);
            hospitals.push_back(h);
            indexById[h->getId()] = h;
        } catch (const std::exception &) { continue; }
    }
}

void HospitalManager::saveToFile() const {
    std::vector<std::vector<std::string>> rows;
    for (const auto &h : hospitals) {
        rows.push_back({h->getId(), h->getName(), std::to_string(h->getLatitude()),
                         std::to_string(h->getLongitude()), std::to_string(h->getTotalBeds()),
                         std::to_string(h->getAvailableBeds()), std::to_string(h->getEmergencyCapacity()),
                         h->getStatus()});
    }
    FileManager::writeCSVAll(dataFile, "id,name,lat,lon,totalBeds,availableBeds,emergencyCapacity,status", rows);
}

std::shared_ptr<Hospital> HospitalManager::addHospital(const std::string &id, const std::string &name,
                                                           double lat, double lon, int totalBeds,
                                                           int availableBeds, int emergencyCapacity) {
    if (exists(id)) throw DuplicateIDException("Hospital ID already exists: " + id);
    auto h = std::make_shared<Hospital>(id, name, lat, lon, totalBeds, availableBeds, emergencyCapacity);
    hospitals.push_back(h);
    indexById[id] = h;
    saveToFile();
    return h;
}

std::shared_ptr<Hospital> HospitalManager::getById(const std::string &id) const {
    auto it = indexById.find(id);
    return it == indexById.end() ? nullptr : it->second;
}

std::vector<std::shared_ptr<Hospital>> HospitalManager::getAll() const { return hospitals; }

bool HospitalManager::exists(const std::string &id) const { return indexById.find(id) != indexById.end(); }

} // namespace drras