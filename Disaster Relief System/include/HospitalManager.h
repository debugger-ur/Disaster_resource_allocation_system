#pragma once
#include <vector>
#include <unordered_map>
#include <memory>
#include <string>
#include "Hospital.h"

namespace drras {

class HospitalManager {
    std::vector<std::shared_ptr<Hospital>> hospitals;
    std::unordered_map<std::string, std::shared_ptr<Hospital>> indexById;
    std::string dataFile;

public:
    explicit HospitalManager(std::string dataFile = "data/hospitals.csv");

    void loadFromFile();
    void saveToFile() const;

    std::shared_ptr<Hospital> addHospital(const std::string &id, const std::string &name,
                                            double lat, double lon, int totalBeds,
                                            int availableBeds, int emergencyCapacity);

    std::shared_ptr<Hospital> getById(const std::string &id) const;
    std::vector<std::shared_ptr<Hospital>> getAll() const;
    bool exists(const std::string &id) const;
};

} // namespace drras