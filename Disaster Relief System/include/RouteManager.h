#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <utility>

namespace drras {

struct RouteResult {
    double distanceKm = 0.0;
    std::vector<std::string> path;
    bool found = false;
};

// Simulated road network: Graph (adjacency list) + Dijkstra shortest path.
// NOTE: Since real road data is not available in this academic version,
// edges are generated from straight-line (Haversine) distances between
// nearby known locations, scaled by a "road factor" to approximate the
// fact that roads are rarely perfectly straight. This is CLEARLY a
// SIMULATED network, not live GPS/road-API data.
class RouteManager {
    struct NodeInfo { double lat; double lon; };

    std::unordered_map<std::string, NodeInfo> nodes;
    std::unordered_map<std::string, std::vector<std::pair<std::string, double>>> adjacency;

public:
    void addLocation(const std::string &name, double lat, double lon);
    void addEdge(const std::string &a, const std::string &b, double weightKm);
    bool hasLocation(const std::string &name) const;

    // Connects every node to its k nearest neighbours to build a sparse,
    // realistic-looking simulated road graph.
    void buildSimulatedNetwork(int kNearest = 3);

    // Dijkstra's algorithm: O((V + E) log V) using a min-priority-queue.
    RouteResult shortestPath(const std::string &source, const std::string &destination) const;

    std::vector<std::string> listLocations() const;
    void clear();
};

} // namespace drras