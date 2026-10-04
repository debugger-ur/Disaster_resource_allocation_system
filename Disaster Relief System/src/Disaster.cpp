#include "Disaster.h"
#include "Exceptions.h"
#include <iostream>
#include <iomanip>

namespace drras {

Disaster::Disaster(std::string id, DisasterType type, Severity severity, int affectedPeople,
                     std::vector<std::string> requiredResources, std::string locationName,
                     double lat, double lon, std::string timestamp, DisasterStatus status)
    : Entity(std::move(id), lat, lon), type(type), severity(severity),
      affectedPeople(affectedPeople), requiredResources(std::move(requiredResources)),
      locationName(std::move(locationName)), timestamp(std::move(timestamp)), status(status) {
    if (affectedPeople < 0) throw InvalidInputException("Affected people count cannot be negative.");
}

long long Disaster::getPriorityScore() const {
    // Severity dominates (weight * 1,000,000) then affected-people count
    // breaks ties -> a CRITICAL disaster always outranks a HIGH one
    // regardless of how many people are affected, matching the spec.
    return static_cast<long long>(severityWeight(severity)) * 1000000LL + affectedPeople;
}

void Disaster::display() const {
    std::cout << "-----------------------------------------\n";
    std::cout << "Disaster ID   : " << id << "\n";
    std::cout << "Type          : " << disasterTypeToString(type) << "\n";
    std::cout << "Severity      : " << severityToString(severity) << "\n";
    std::cout << "Affected      : " << affectedPeople << "\n";
    std::cout << "Location      : " << locationName
              << " (" << std::fixed << std::setprecision(4) << latitude
              << ", " << longitude << ")\n";
    std::cout << "Required      : ";
    for (size_t i = 0; i < requiredResources.size(); ++i) {
        std::cout << requiredResources[i] << (i + 1 < requiredResources.size() ? ", " : "");
    }
    std::cout << "\nReported At   : " << timestamp << "\n";
    std::cout << "Status        : " << disasterStatusToString(status) << "\n";
    std::cout << "-----------------------------------------\n";
}

} // namespace drras