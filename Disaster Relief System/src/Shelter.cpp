#include "Shelter.h"
#include "Exceptions.h"
#include <iostream>
#include <iomanip>

namespace drras {

Shelter::Shelter(std::string id, std::string name, double lat, double lon, int capacity, int occupied)
    : Entity(std::move(id), lat, lon), name(std::move(name)), capacity(capacity), occupied(occupied) {
    if (capacity < 0 || occupied < 0) throw InvalidInputException("Shelter capacity/occupied cannot be negative.");
    if (occupied > capacity) throw InvalidInputException("Occupied count cannot exceed capacity.");
}

void Shelter::accommodate(int count) {
    if (count < 0) throw InvalidInputException("Count cannot be negative.");
    if (occupied + count > capacity) throw InvalidInputException("Shelter " + id + " does not have enough space.");
    occupied += count;
}

void Shelter::display() const {
    std::cout << "-----------------------------------------\n";
    std::cout << "Shelter ID    : " << id << "\n";
    std::cout << "Name          : " << name << "\n";
    std::cout << "Location      : (" << std::fixed << std::setprecision(4)
              << latitude << ", " << longitude << ")\n";
    std::cout << "Capacity      : " << capacity << "\n";
    std::cout << "Occupied      : " << occupied << "\n";
    std::cout << "Available     : " << getAvailableCapacity() << "\n";
    std::cout << "-----------------------------------------\n";
}

} // namespace drras