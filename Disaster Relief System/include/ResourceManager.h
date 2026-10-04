#pragma once
#include <vector>
#include <unordered_map>
#include <memory>
#include <string>
#include "Resource.h"

namespace drras {

class ResourceManager {
    std::vector<std::shared_ptr<Resource>> resources;
    std::unordered_map<std::string, std::shared_ptr<Resource>> indexById;
    std::string dataFile;

    static std::shared_ptr<Resource> createResource(
        const std::string &category, const std::string &id, const std::string &type,
        int quantity, ResourceStatus status, double lat, double lon,
        const std::string &locationName, int priority, const std::string &contact);

public:
    explicit ResourceManager(std::string dataFile = "data/resources.csv");

    void loadFromFile();
    void saveToFile() const;

    std::shared_ptr<Resource> addResource(const std::string &category, const std::string &id,
                                            const std::string &type, int quantity, double lat, double lon,
                                            const std::string &locationName, int priority,
                                            const std::string &contact);

    std::shared_ptr<Resource> getById(const std::string &id) const;
    std::vector<std::shared_ptr<Resource>> getAll() const;
    std::vector<std::shared_ptr<Resource>> getByCategory(const std::string &category) const;
    std::vector<std::shared_ptr<Resource>> getAvailableByCategory(const std::string &category) const;

    bool updateStatus(const std::string &id, ResourceStatus status);
    bool exists(const std::string &id) const;

    int countAvailable() const;
    int countDispatched() const;
};

} // namespace drras