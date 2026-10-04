#include "Allocation.h"
#include <iostream>
#include <iomanip>

namespace drras {

void Allocation::display() const {
    std::cout << "-----------------------------------------\n";
    std::cout << "Allocation ID : " << allocationId << "\n";
    std::cout << "Disaster      : " << disasterId << "\n";
    std::cout << "Resource      : " << resourceId << " [" << resourceCategory << "]\n";
    std::cout << "Distance      : " << std::fixed << std::setprecision(2) << distanceKm << " km\n";
    std::cout << "Timestamp     : " << timestamp << "\n";
    std::cout << "Status        : " << status << "\n";
    std::cout << "-----------------------------------------\n";
}

} // namespace drras