#pragma once
#include <list>
#include <vector>
#include <unordered_map>
#include <queue>
#include <memory>
#include <string>
#include "Disaster.h"

namespace drras {

// Comparator for the priority_queue: higher priority score = more urgent
// = processed first (max-heap behaviour via std::priority_queue default).
struct DisasterPriorityComparator {
    bool operator()(const std::shared_ptr<Disaster> &a, const std::shared_ptr<Disaster> &b) const {
        return a->getPriorityScore() < b->getPriorityScore();
    }
};

class DisasterManager {
    std::list<std::shared_ptr<Disaster>> records;                  // dynamic linked list
    std::unordered_map<std::string, std::shared_ptr<Disaster>> indexById; // O(1) search
    std::priority_queue<std::shared_ptr<Disaster>, std::vector<std::shared_ptr<Disaster>>,
                         DisasterPriorityComparator> pendingQueue;   // emergency ordering
    std::string dataFile;

public:
    explicit DisasterManager(std::string dataFile = "data/disasters.csv");

    void loadFromFile();
    void saveToFile() const;

    std::shared_ptr<Disaster> addDisaster(const std::string &id, DisasterType type, Severity severity,
                                            int affected, const std::vector<std::string> &requiredResources,
                                            const std::string &locationName, double lat, double lon);

    std::shared_ptr<Disaster> getById(const std::string &id) const;
    std::vector<std::shared_ptr<Disaster>> getAllDisasters() const;
    std::vector<std::shared_ptr<Disaster>> getActiveDisasters() const;
    bool resolveDisaster(const std::string &id);
    bool exists(const std::string &id) const;

    std::shared_ptr<Disaster> peekNextPriority();
    std::shared_ptr<Disaster> popNextPriority();
};

} // namespace drras