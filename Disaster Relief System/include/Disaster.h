#pragma once
#include "Entity.h"
#include "Common.h"
#include <vector>
#include <string>

namespace drras {

class Disaster : public Entity {
    DisasterType type;
    Severity severity;
    int affectedPeople;
    std::vector<std::string> requiredResources; // e.g. {"Ambulance","MedicalTeam"}
    std::string locationName;
    std::string timestamp;
    DisasterStatus status;

public:
    Disaster(std::string id, DisasterType type, Severity severity, int affectedPeople,
              std::vector<std::string> requiredResources, std::string locationName,
              double lat, double lon,
              std::string timestamp = currentTimestamp(),
              DisasterStatus status = DisasterStatus::ACTIVE);

    DisasterType getType() const { return type; }
    Severity getSeverity() const { return severity; }
    int getAffectedPeople() const { return affectedPeople; }
    const std::vector<std::string>& getRequiredResources() const { return requiredResources; }
    const std::string& getLocationName() const { return locationName; }
    const std::string& getTimestamp() const { return timestamp; }
    DisasterStatus getStatus() const { return status; }
    void setStatus(DisasterStatus s) { status = s; }

    // Used by the priority queue: severity dominates, affected count breaks ties.
    long long getPriorityScore() const;

    void display() const override;
};

} // namespace drras