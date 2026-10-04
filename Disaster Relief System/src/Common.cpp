#include "Common.h"
#include "Exceptions.h"
#include <ctime>
#include <sstream>
#include <iomanip>

namespace drras {

std::string disasterTypeToString(DisasterType t) {
    switch (t) {
        case DisasterType::FLOOD: return "FLOOD";
        case DisasterType::EARTHQUAKE: return "EARTHQUAKE";
        case DisasterType::FIRE: return "FIRE";
        case DisasterType::LANDSLIDE: return "LANDSLIDE";
        case DisasterType::INDUSTRIAL_ACCIDENT: return "INDUSTRIAL_ACCIDENT";
        default: return "OTHER";
    }
}

DisasterType stringToDisasterType(const std::string &s) {
    if (s == "FLOOD") return DisasterType::FLOOD;
    if (s == "EARTHQUAKE") return DisasterType::EARTHQUAKE;
    if (s == "FIRE") return DisasterType::FIRE;
    if (s == "LANDSLIDE") return DisasterType::LANDSLIDE;
    if (s == "INDUSTRIAL_ACCIDENT") return DisasterType::INDUSTRIAL_ACCIDENT;
    if (s == "OTHER") return DisasterType::OTHER;
    throw InvalidInputException("Unknown disaster type: " + s);
}

std::string severityToString(Severity s) {
    switch (s) {
        case Severity::CRITICAL: return "CRITICAL";
        case Severity::HIGH: return "HIGH";
        case Severity::MEDIUM: return "MEDIUM";
        default: return "LOW";
    }
}

Severity stringToSeverity(const std::string &s) {
    if (s == "CRITICAL") return Severity::CRITICAL;
    if (s == "HIGH") return Severity::HIGH;
    if (s == "MEDIUM") return Severity::MEDIUM;
    if (s == "LOW") return Severity::LOW;
    throw InvalidInputException("Unknown severity: " + s);
}

int severityWeight(Severity s) {
    switch (s) {
        case Severity::CRITICAL: return 4;
        case Severity::HIGH: return 3;
        case Severity::MEDIUM: return 2;
        default: return 1;
    }
}

std::string resourceStatusToString(ResourceStatus s) {
    switch (s) {
        case ResourceStatus::AVAILABLE: return "AVAILABLE";
        case ResourceStatus::DISPATCHED: return "DISPATCHED";
        case ResourceStatus::UNAVAILABLE: return "UNAVAILABLE";
        default: return "MAINTENANCE";
    }
}

ResourceStatus stringToResourceStatus(const std::string &s) {
    if (s == "AVAILABLE") return ResourceStatus::AVAILABLE;
    if (s == "DISPATCHED") return ResourceStatus::DISPATCHED;
    if (s == "UNAVAILABLE") return ResourceStatus::UNAVAILABLE;
    if (s == "MAINTENANCE") return ResourceStatus::MAINTENANCE;
    throw InvalidInputException("Unknown resource status: " + s);
}

std::string disasterStatusToString(DisasterStatus s) {
    return s == DisasterStatus::ACTIVE ? "ACTIVE" : "RESOLVED";
}

DisasterStatus stringToDisasterStatus(const std::string &s) {
    if (s == "ACTIVE") return DisasterStatus::ACTIVE;
    if (s == "RESOLVED") return DisasterStatus::RESOLVED;
    throw InvalidInputException("Unknown disaster status: " + s);
}

std::string currentTimestamp() {
    std::time_t t = std::time(nullptr);
    std::tm tmBuf{};
#if defined(_WIN32)
    localtime_s(&tmBuf, &t);
#else
    localtime_r(&t, &tmBuf);
#endif
    std::ostringstream oss;
    oss << std::put_time(&tmBuf, "%Y-%m-%d %H:%M:%S");
    return oss.str();
}

} // namespace drras