#pragma once
#include "Entity.h"
#include <string>

namespace drras {

class Shelter : public Entity {
    std::string name;
    int capacity;
    int occupied;

public:
    Shelter(std::string id, std::string name, double lat, double lon,
             int capacity, int occupied);

    const std::string& getName() const { return name; }
    int getCapacity() const { return capacity; }
    int getOccupied() const { return occupied; }
    int getAvailableCapacity() const { return capacity - occupied; }

    void accommodate(int count); // throws if over capacity
    void display() const override;
};

} // namespace drras