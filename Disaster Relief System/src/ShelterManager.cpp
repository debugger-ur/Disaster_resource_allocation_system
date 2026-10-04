#include "ShelterManager.h"
#include "FileManager.h"
#include "Exceptions.h"

namespace drras {

ShelterManager::ShelterManager(std::string dataFile) : dataFile(std::move(dataFile)) {
    loadFromFile();
}

void ShelterManager::loadFromFile() {
    const std::string header = "id,name,lat,lon,capacity,occupied";
    FileManager::ensureFile(dataFile, header);
    auto rows = FileManager::readCSV(dataFile);

    for (const auto &row : rows) {
        if (row.size() < 6) continue;
        try {
            auto s = std::make_shared<Shelter>(row[0], row[1], std::stod(row[2]), std::stod(row[3]),
                                                 std::stoi(row[4]), std::stoi(row[5]));
            shelters.push_back(s);
            indexById[s->getId()] = s;
        } catch (const std::exception &) { continue; }
    }
}

void ShelterManager::saveToFile() const {
    std::vector<std::vector<std::string>> rows;
    for (const auto &s : shelters) {
        rows.push_back({s->getId(), s->getName(), std::to_string(s->getLatitude()),
                         std::to_string(s->getLongitude()), std::to_string(s->getCapacity()),
                         std::to_string(s->getOccupied())});
    }
    FileManager::writeCSVAll(dataFile, "id,name,lat,lon,capacity,occupied", rows);
}

std::shared_ptr<Shelter> ShelterManager::addShelter(const std::string &id, const std::string &name,
                                                       double lat, double lon, int capacity, int occupied) {
    if (exists(id)) throw DuplicateIDException("Shelter ID already exists: " + id);
    auto s = std::make_shared<Shelter>(id, name, lat, lon, capacity, occupied);
    shelters.push_back(s);
    indexById[id] = s;
    saveToFile();
    return s;
}

std::shared_ptr<Shelter> ShelterManager::getById(const std::string &id) const {
    auto it = indexById.find(id);
    return it == indexById.end() ? nullptr : it->second;
}

std::vector<std::shared_ptr<Shelter>> ShelterManager::getAll() const { return shelters; }

bool ShelterManager::exists(const std::string &id) const { return indexById.find(id) != indexById.end(); }

} // namespace drras\