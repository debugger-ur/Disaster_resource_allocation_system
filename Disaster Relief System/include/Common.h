#pragma once
#include <string>

// Shared enums + utility free-functions used across the whole system.
namespace drras {

enum class DisasterType { FLOOD, EARTHQUAKE, FIRE, LANDSLIDE, INDUSTRIAL_ACCIDENT, OTHER };
enum class Severity { CRITICAL = 1, HIGH = 2, MEDIUM = 3, LOW = 4 };
enum class ResourceStatus { AVAILABLE, DISPATCHED, UNAVAILABLE, MAINTENANCE };
enum class DisasterStatus { ACTIVE, RESOLVED };

std::string disasterTypeToString(DisasterType t);
DisasterType stringToDisasterType(const std::string &s);

std::string severityToString(Severity s);
Severity stringToSeverity(const std::string &s);
int severityWeight(Severity s); // higher = more urgent (CRITICAL=4 ... LOW=1)

std::string resourceStatusToString(ResourceStatus s);
ResourceStatus stringToResourceStatus(const std::string &s);

std::string disasterStatusToString(DisasterStatus s);
DisasterStatus stringToDisasterStatus(const std::string &s);

std::string currentTimestamp();

} // namespace drras