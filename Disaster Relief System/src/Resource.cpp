#include "Resource.h"
#include "Exceptions.h"
#include <iostream>
#include <iomanip>

namespace drras {

Resource::Resource(std::string id, std::string type, int quantity, ResourceStatus status,
                     double lat, double lon, std::string locationName, int priority,
                     std::string contactInfo)
    : Entity(std::move(id), lat, lon), type(std::move(type)), quantity(quantity), status(status),
      priority(priority), contactInfo(std::move(contactInfo)), currentLocationName(std::move(locationName)) {
    if (quantity < 0) throw InvalidInputException("Resource quantity cannot be negative.");
    if (priority < 1 || priority > 5) throw InvalidInputException("Resource priority must be between 1 and 5.");
}

void Resource::display() const {
    std::cout << "-----------------------------------------\n";
    std::cout << "Resource ID   : " << id << "\n";
    std::cout << "Category      : " << getCategory() << "\n";   // polymorphic call
    std::cout << "Type          : " << type << "\n";
    std::cout << "Quantity      : " << quantity << "\n";
    std::cout << "Status        : " << resourceStatusToString(status) << "\n";
    std::cout << "Location      : " << currentLocationName
              << " (" << std::fixed << std::setprecision(4) << latitude
              << ", " << longitude << ")\n";
    std::cout << "Priority      : " << priority << "\n";
    std::cout << "Contact       : " << (contactInfo.empty() ? "N/A" : contactInfo) << "\n";
    std::cout << "-----------------------------------------\n";
}

} // namespace drras