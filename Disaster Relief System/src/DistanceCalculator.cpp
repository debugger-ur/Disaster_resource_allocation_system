#include "DistanceCalculator.h"
#include <cmath>

namespace drras {

// Haversine formula:
// a = sin^2(d_lat/2) + cos(lat1)*cos(lat2)*sin^2(d_lon/2)
// c = 2 * atan2(sqrt(a), sqrt(1-a))
// distance = R * c   (R = mean Earth radius = 6371 km)
// Time complexity: O(1)
double DistanceCalculator::haversineDistanceKm(double lat1, double lon1, double lat2, double lon2) {
    constexpr double EARTH_RADIUS_KM = 6371.0;
    constexpr double DEG_TO_RAD = M_PI / 180.0;

    double dLat = (lat2 - lat1) * DEG_TO_RAD;
    double dLon = (lon2 - lon1) * DEG_TO_RAD;

    double rLat1 = lat1 * DEG_TO_RAD;
    double rLat2 = lat2 * DEG_TO_RAD;

    double a = std::sin(dLat / 2) * std::sin(dLat / 2) +
               std::cos(rLat1) * std::cos(rLat2) * std::sin(dLon / 2) * std::sin(dLon / 2);
    double c = 2 * std::atan2(std::sqrt(a), std::sqrt(1 - a));

    return EARTH_RADIUS_KM * c;
}

double DistanceCalculator::distanceBetween(const Entity &a, const Entity &b) {
    return haversineDistanceKm(a.getLatitude(), a.getLongitude(), b.getLatitude(), b.getLongitude());
}

} // namespace drras