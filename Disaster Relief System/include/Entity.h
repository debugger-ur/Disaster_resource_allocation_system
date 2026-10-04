#pragma once
#include <string>

namespace drras {

// Abstract base class — demonstrates ABSTRACTION & common ENCAPSULATED state
// shared by every geo-located object in the system.
class Entity {
protected:
    std::string id;
    double latitude;
    double longitude;

public:
    Entity(std::string id_, double lat, double lon);
    virtual ~Entity() = default;

    const std::string& getId() const { return id; }
    double getLatitude() const { return latitude; }
    double getLongitude() const { return longitude; }

    virtual void display() const = 0; // pure virtual -> POLYMORPHISM
};

} // namespace drras