#pragma once
#include <vector>
#include <unordered_map>
#include <memory>
#include <string>
#include "Shelter.h"

namespace drras {

class ShelterManager {
    std::vector<std::shared_ptr<Shelter>> shelters;
    std::unordered_map<std::string, std::shared_ptr<Shelter>> indexById;
    std::string dataFile;

public:
    explicit ShelterManager(std::string dataFile = "data/shelters.csv");

    void loadFromFile();
    void saveToFile() const;

    std::shared_ptr<Shelter> addShelter(const std::string &id, const std::string &name,
                                          double lat, double lon, int capacity, int occupied);

    std::shared_ptr<Shelter> getById(const std::string &id) const;
    std::vector<std::shared_ptr<Shelter>> getAll() const;
    bool exists(const std::string &id) const;
};

} // namespace drras