#pragma once
#include "Entity.h"
#include "Common.h"
#include <string>

namespace drras {

// Abstract base for every dispatchable relief resource.
class Resource : public Entity {
protected:
    std::string type;           // e.g. "ALS", "Food", "HeavyMachinery"
    int quantity;                // capacity / units
    ResourceStatus status;
    int priority;                 // 1 (highest) .. 5 (lowest) intrinsic priority
    std::string contactInfo;
    std::string currentLocationName;

public:
    Resource(std::string id, std::string type, int quantity, ResourceStatus status,
              double lat, double lon, std::string locationName, int priority,
              std::string contactInfo);
    ~Resource() override = default;

    virtual std::string getCategory() const = 0; // POLYMORPHISM hook

    const std::string& getType() const { return type; }
    int getQuantity() const { return quantity; }
    ResourceStatus getStatus() const { return status; }
    void setStatus(ResourceStatus s) { status = s; }
    bool isAvailable() const { return status == ResourceStatus::AVAILABLE; }
    int getPriority() const { return priority; }
    const std::string& getContactInfo() const { return contactInfo; }
    const std::string& getCurrentLocationName() const { return currentLocationName; }

    void display() const override;
};

// ---- Concrete resource categories (INHERITANCE) ----
class Ambulance : public Resource {
public:
    using Resource::Resource;
    std::string getCategory() const override { return "Ambulance"; }
};

class RescueTeam : public Resource {
public:
    using Resource::Resource;
    std::string getCategory() const override { return "RescueTeam"; }
};

class MedicalTeam : public Resource {
public:
    using Resource::Resource;
    std::string getCategory() const override { return "MedicalTeam"; }
};

class Equipment : public Resource { // rescue equipment / heavy machinery
public:
    using Resource::Resource;
    std::string getCategory() const override { return "Equipment"; }
};

class Supply : public Resource { // food / water / medicines
public:
    using Resource::Resource;
    std::string getCategory() const override { return "Supply"; }
};

} // namespace drras