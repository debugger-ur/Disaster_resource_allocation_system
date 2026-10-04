#include "DisasterManager.h"
#include "FileManager.h"
#include "Exceptions.h"

namespace drras {

DisasterManager::DisasterManager(std::string dataFile) : dataFile(std::move(dataFile)) {
    loadFromFile();
}

void DisasterManager::loadFromFile() {
    const std::string header = "id,type,severity,affected,requiredResources,locationName,lat,lon,timestamp,status";
    FileManager::ensureFile(dataFile, header);
    auto rows = FileManager::readCSV(dataFile);

    for (const auto &row : rows) {
        if (row.size() < 10) continue; // skip malformed rows defensively
        try {
            std::vector<std::string> required = FileManager::splitLine(row[4], ';');
            if (required.size() == 1 && required[0].empty()) required.clear();

            auto disaster = std::make_shared<Disaster>(
                row[0], stringToDisasterType(row[1]), stringToSeverity(row[2]),
                std::stoi(row[3]), required, row[5], std::stod(row[6]), std::stod(row[7]),
                row[8], stringToDisasterStatus(row[9]));

            records.push_back(disaster);
            indexById[disaster->getId()] = disaster;
            if (disaster->getStatus() == DisasterStatus::ACTIVE) pendingQueue.push(disaster);
        } catch (const std::exception &) {
            // skip corrupted row, continue loading the rest
            continue;
        }
    }
}

void DisasterManager::saveToFile() const {
    std::vector<std::vector<std::string>> rows;
    for (const auto &d : records) {
        std::string required;
        const auto &req = d->getRequiredResources();
        for (size_t i = 0; i < req.size(); ++i) {
            required += req[i];
            if (i + 1 < req.size()) required += ";";
        }
        rows.push_back({
            d->getId(), disasterTypeToString(d->getType()), severityToString(d->getSeverity()),
            std::to_string(d->getAffectedPeople()), required, d->getLocationName(),
            std::to_string(d->getLatitude()), std::to_string(d->getLongitude()),
            d->getTimestamp(), disasterStatusToString(d->getStatus())
        });
    }
    FileManager::writeCSVAll(dataFile,
        "id,type,severity,affected,requiredResources,locationName,lat,lon,timestamp,status", rows);
}

std::shared_ptr<Disaster> DisasterManager::addDisaster(
    const std::string &id, DisasterType type, Severity severity, int affected,
    const std::vector<std::string> &requiredResources, const std::string &locationName,
    double lat, double lon) {

    if (exists(id)) throw DuplicateIDException("Disaster ID already exists: " + id);

    auto disaster = std::make_shared<Disaster>(id, type, severity, affected, requiredResources,
                                                 locationName, lat, lon);
    records.push_back(disaster);
    indexById[id] = disaster;
    pendingQueue.push(disaster);
    saveToFile();
    return disaster;
}

std::shared_ptr<Disaster> DisasterManager::getById(const std::string &id) const {
    auto it = indexById.find(id);
    return it == indexById.end() ? nullptr : it->second;
}

std::vector<std::shared_ptr<Disaster>> DisasterManager::getAllDisasters() const {
    return {records.begin(), records.end()};
}

std::vector<std::shared_ptr<Disaster>> DisasterManager::getActiveDisasters() const {
    std::vector<std::shared_ptr<Disaster>> result;
    for (const auto &d : records) if (d->getStatus() == DisasterStatus::ACTIVE) result.push_back(d);
    return result;
}

bool DisasterManager::resolveDisaster(const std::string &id) {
    auto it = indexById.find(id);
    if (it == indexById.end()) return false;
    it->second->setStatus(DisasterStatus::RESOLVED);
    saveToFile();
    return true;
}

bool DisasterManager::exists(const std::string &id) const {
    return indexById.find(id) != indexById.end();
}

std::shared_ptr<Disaster> DisasterManager::peekNextPriority() {
    while (!pendingQueue.empty() && pendingQueue.top()->getStatus() == DisasterStatus::RESOLVED)
        pendingQueue.pop();
    return pendingQueue.empty() ? nullptr : pendingQueue.top();
}

std::shared_ptr<Disaster> DisasterManager::popNextPriority() {
    auto next = peekNextPriority();
    if (next) pendingQueue.pop();
    return next;
}

} // namespace drras