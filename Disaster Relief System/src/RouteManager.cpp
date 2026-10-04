#include "RouteManager.h"
#include "DistanceCalculator.h"
#include <queue>
#include <set>
#include <limits>
#include <algorithm>

namespace drras {

void RouteManager::addLocation(const std::string &name, double lat, double lon) {
    nodes[name] = {lat, lon};
    if (adjacency.find(name) == adjacency.end()) adjacency[name] = {};
}

bool RouteManager::hasLocation(const std::string &name) const {
    return nodes.find(name) != nodes.end();
}

void RouteManager::addEdge(const std::string &a, const std::string &b, double weightKm) {
    if (!hasLocation(a) || !hasLocation(b)) return;
    // avoid duplicate edges between the same pair
    auto &listA = adjacency[a];
    bool exists = std::any_of(listA.begin(), listA.end(),
                               [&](const auto &p) { return p.first == b; });
    if (!exists) {
        adjacency[a].push_back({b, weightKm});
        adjacency[b].push_back({a, weightKm});
    }
}

void RouteManager::buildSimulatedNetwork(int kNearest) {
    // Road-factor: real roads are never perfectly straight, so we scale
    // the straight-line Haversine distance up slightly to simulate this.
    constexpr double ROAD_FACTOR = 1.15;

    for (const auto &[name, info] : nodes) {
        std::vector<std::pair<std::string, double>> distances;
        for (const auto &[otherName, otherInfo] : nodes) {
            if (otherName == name) continue;
            double d = DistanceCalculator::haversineDistanceKm(info.lat, info.lon, otherInfo.lat, otherInfo.lon);
            distances.push_back({otherName, d});
        }
        std::sort(distances.begin(), distances.end(),
                  [](const auto &a, const auto &b) { return a.second < b.second; });

        int connections = std::min(static_cast<int>(distances.size()), kNearest);
        for (int i = 0; i < connections; ++i) {
            addEdge(name, distances[i].first, distances[i].second * ROAD_FACTOR);
        }
    }
}

// Dijkstra's single-source shortest path with early exit once destination
// is finalized. Complexity: O((V + E) log V) using a binary heap.
RouteResult RouteManager::shortestPath(const std::string &source, const std::string &destination) const {
    RouteResult result;
    if (!hasLocation(source) || !hasLocation(destination)) return result;

    std::unordered_map<std::string, double> dist;
    std::unordered_map<std::string, std::string> prev;
    for (const auto &[name, _] : nodes) dist[name] = std::numeric_limits<double>::infinity();
    dist[source] = 0.0;

    using PQItem = std::pair<double, std::string>;
    std::priority_queue<PQItem, std::vector<PQItem>, std::greater<PQItem>> pq;
    pq.push({0.0, source});
    std::set<std::string> visited;

    while (!pq.empty()) {
        auto [d, u] = pq.top();
        pq.pop();
        if (visited.count(u)) continue;
        visited.insert(u);
        if (u == destination) break;

        auto it = adjacency.find(u);
        if (it == adjacency.end()) continue;
        for (const auto &[v, w] : it->second) {
            double newDist = dist[u] + w;
            if (newDist < dist[v]) {
                dist[v] = newDist;
                prev[v] = u;
                pq.push({newDist, v});
            }
        }
    }

    if (dist[destination] == std::numeric_limits<double>::infinity()) return result;

    std::vector<std::string> path;
    std::string cur = destination;
    while (true) {
        path.push_back(cur);
        if (cur == source) break;
        auto it = prev.find(cur);
        if (it == prev.end()) return result; // disconnected safeguard
        cur = it->second;
    }
    std::reverse(path.begin(), path.end());

    result.distanceKm = dist[destination];
    result.path = path;
    result.found = true;
    return result;
}

std::vector<std::string> RouteManager::listLocations() const {
    std::vector<std::string> names;
    names.reserve(nodes.size());
    for (const auto &[name, _] : nodes) names.push_back(name);
    return names;
}

void RouteManager::clear() {
    nodes.clear();
    adjacency.clear();
}

} // namespace drras