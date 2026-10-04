#pragma once
#include <vector>
#include <memory>
#include <utility>
#include <algorithm>
#include "Entity.h"

namespace drras {

// Dedicated, UI-independent module for all geo-distance logic.
// Demonstrates static-utility style ABSTRACTION (no instances needed).
class DistanceCalculator {
public:
    DistanceCalculator() = delete;

    // Core Haversine formula -> distance in kilometers. O(1).
    static double haversineDistanceKm(double lat1, double lon1, double lat2, double lon2);
    static double distanceBetween(const Entity &a, const Entity &b);

    // Generic distance-sort for any Entity-derived type held in shared_ptr.
    // O(n) distance computation + O(n log n) sort.
    template <typename T>
    static std::vector<std::pair<std::shared_ptr<T>, double>>
    sortByDistance(const std::vector<std::shared_ptr<T>> &items, double lat, double lon) {
        std::vector<std::pair<std::shared_ptr<T>, double>> result;
        result.reserve(items.size());
        for (const auto &item : items) {
            double d = haversineDistanceKm(lat, lon, item->getLatitude(), item->getLongitude());
            result.emplace_back(item, d);
        }
        std::sort(result.begin(), result.end(),
                  [](const auto &a, const auto &b) { return a.second < b.second; });
        return result;
    }

    // Returns the single nearest item, or nullptr if the list is empty.
    template <typename T>
    static std::shared_ptr<T> findNearest(const std::vector<std::shared_ptr<T>> &items,
                                            double lat, double lon, double *outDistance = nullptr) {
        if (items.empty()) return nullptr;
        auto sorted = sortByDistance(items, lat, lon);
        if (outDistance) *outDistance = sorted.front().second;
        return sorted.front().first;
    }
};

} // namespace drras