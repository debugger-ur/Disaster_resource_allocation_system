#pragma once
#include "Entity.h"
#include <string>

namespace drras {

class Hospital : public Entity {
    std::string name;
    int totalBeds;
    int availableBeds;
    int emergencyCapacity;
    std::string status; // OPERATIONAL / FULL / CLOSED

public:
    Hospital(std::string id, std::string name, double lat, double lon,
              int totalBeds, int availableBeds, int emergencyCapacity,
              std::string status = "OPERATIONAL");

    const std::string& getName() const { return name; }
    int getTotalBeds() const { return totalBeds; }
    int getAvailableBeds() const { return availableBeds; }
    int getEmergencyCapacity() const { return emergencyCapacity; }
    const std::string& getStatus() const { return status; }

    void admitPatients(int count); // throws if not enough beds
    void display() const override;
};

} // namespace drras