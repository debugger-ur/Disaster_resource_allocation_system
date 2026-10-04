#pragma once
#include <string>

namespace drras {

// A lightweight record describing one resource -> disaster dispatch.
struct Allocation {
    std::string allocationId;
    std::string disasterId;
    std::string resourceId;
    std::string resourceCategory;
    double distanceKm = 0.0;
    std::string timestamp;
    std::string status; // DISPATCHED

    void display() const;
};

} // namespace drras