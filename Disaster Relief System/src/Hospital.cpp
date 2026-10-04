#include "Hospital.h"
#include "Exceptions.h"
#include <iostream>
#include <iomanip>

namespace drras {

Hospital::Hospital(std::string id, std::string name, double lat, double lon,
                     int totalBeds, int availableBeds, int emergencyCapacity, std::string status)
    : Entity(std::move(id), lat, lon), name(std::move(name)), totalBeds(totalBeds),
      availableBeds(availableBeds), emergencyCapacity(emergencyCapacity), status(std::move(status)) {
    if (totalBeds < 0 || availableBeds < 0 || emergencyCapacity < 0)
        throw InvalidInputException("Hospital bed counts cannot be negative.");
    if (availableBeds > totalBeds)
        throw InvalidInputException("Available beds cannot exceed total beds.");
}

void Hospital::admitPatients(int count) {
    if (count < 0) throw InvalidInputException("Patient count cannot be negative.");
    if (count > availableBeds) throw InvalidInputException("Not enough available beds in hospital " + id);
    availableBeds -= count;
}

void Hospital::display() const {
    std::cout << "-----------------------------------------\n";
    std::cout << "Hospital ID   : " << id << "\n";
    std::cout << "Name          : " << name << "\n";
    std::cout << "Location      : (" << std::fixed << std::setprecision(4)
              << latitude << ", " << longitude << ")\n";
    std::cout << "Total Beds    : " << totalBeds << "\n";
    std::cout << "Available     : " << availableBeds << "\n";
    std::cout << "Emergency Cap : " << emergencyCapacity << "\n";
    std::cout << "Status        : " << status << "\n";
    std::cout << "-----------------------------------------\n";
}

} // namespace drras