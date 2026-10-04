#include "Entity.h"
#include "Exceptions.h"

namespace drras {

Entity::Entity(std::string id_, double lat, double lon)
    : id(std::move(id_)), latitude(lat), longitude(lon) {
    if (id.empty()) throw InvalidInputException("Entity ID cannot be empty.");
    if (lat < -90.0 || lat > 90.0) throw InvalidInputException("Latitude must be between -90 and 90.");
    if (lon < -180.0 || lon > 180.0) throw InvalidInputException("Longitude must be between -180 and 180.");
}

} // namespace drras