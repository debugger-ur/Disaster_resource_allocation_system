import { haversineDistanceKm } from "./distanceCalculator.js";

export class RouteManager {
  constructor() {
    this.nodes = new Map();
    this.adjacency = new Map();
  }

  addLocation(name, lat, lon) {
    this.nodes.set(name, { lat, lon });
    if (!this.adjacency.has(name)) this.adjacency.set(name, []);
  }

  addEdge(a, b, weight) {
    if (!this.nodes.has(a) || !this.nodes.has(b)) return;
    const listA = this.adjacency.get(a);
    if (!listA.some((e) => e.to === b)) {
      listA.push({ to: b, weight });
      this.adjacency.get(b).push({ to: a, weight });
    }
  }

  // Builds a sparse simulated road graph from k-nearest neighbours.
  buildSimulatedNetwork(kNearest = 3) {
    const ROAD_FACTOR = 1.15; // roads are rarely perfectly straight
    for (const [name, info] of this.nodes) {
      const distances = [];
      for (const [other, otherInfo] of this.nodes) {
        if (other === name) continue;
        distances.push({ name: other, dist: haversineDistanceKm(info.lat, info.lon, otherInfo.lat, otherInfo.lon) });
      }
      distances.sort((a, b) => a.dist - b.dist);
      distances.slice(0, kNearest).forEach((d) => this.addEdge(name, d.name, d.dist * ROAD_FACTOR));
    }
  }

  // Dijkstra's shortest path algorithm — O((V+E) log V) with array-based PQ (fine for small graphs).
  shortestPath(source, destination) {
    if (!this.nodes.has(source) || !this.nodes.has(destination)) {
      return { found: false, distance: 0, path: [] };
    }
    const dist = new Map();
    const prev = new Map();
    for (const name of this.nodes.keys()) dist.set(name, Infinity);
    dist.set(source, 0);

    const visited = new Set();
    const queue = [[0, source]];

    while (queue.length) {
      queue.sort((a, b) => a[0] - b[0]);
      const [d, u] = queue.shift();
      if (visited.has(u)) continue;
      visited.add(u);
      if (u === destination) break;

      for (const { to, weight } of this.adjacency.get(u) || []) {
        const newDist = d + weight;
        if (newDist < dist.get(to)) {
          dist.set(to, newDist);
          prev.set(to, u);
          queue.push([newDist, to]);
        }
      }
    }

    if (dist.get(destination) === Infinity) return { found: false, distance: 0, path: [] };

    const path = [];
    let cur = destination;
    while (cur !== undefined) {
      path.unshift(cur);
      if (cur === source) break;
      cur = prev.get(cur);
    }
    return { found: true, distance: dist.get(destination), path };
  }

  listLocations() { return [...this.nodes.keys()]; }
  clear() { this.nodes.clear(); this.adjacency.clear(); }
}
