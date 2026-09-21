# Disaster_resource_allocation_system
Automated disaster relief triage and supply dispatch system in C++
# Disaster Resource Allocation System

A priority-aware relief resource allocation system that automatically tracks disaster-relief requests and resources, and matches supply to demand based on urgency and proximity — built for **DS in C & OOPs with C++ (DSCPP-III-2026-T100)**.

## Problem Statement / Objective

During disasters such as floods, earthquakes, and fires, relief resources (food, medical supplies, shelter, volunteers) are typically allocated manually by control rooms and NGOs using phone calls, spreadsheets, and radio communication. This process is slow, error-prone, and often leads to mismatched supply and demand — some relief centers stay over-stocked while nearby affected zones remain underserved, even though every minute of delay directly affects survival and well-being.

Existing logistics/inventory-management tools are generic and not disaster-specific: they lack urgency ranking, dynamic zone accessibility, and real-time volunteer availability, leaving allocation decisions dependent on individual coordinator experience rather than a systematic, data-driven process.

**Goal:** Automatically track disaster-relief requests and resources, and allocate resources based on urgency and proximity, reducing response time and ensuring the most urgent requests are served first.

## Team

**Team DSCPP-III-2026-T100** — Semester 3

| Role | Name | Student ID | Section | Email |
|---|---|---|---|---|
| Team Lead | Shubham Bisht | 2510012245 | F | bishtshubham265@gmail.com |
| Member | Samiksha Bhandari | 2510010580 | DS1 | bhandarisamiksha22@gmail.com |
| Member | Sarthak Semwal | 2510010180 | ML4 | sarthaksemwal92@gmail.com |
| Member | Nikhil Singh Rawat | 2510012376 | DS2 | nikhil.singh0072@gmail.com |

## Technologies / Tools Used

- **Language:** C (core data structures), C++ (OOP layer, STL)
- **Data structures:** Graphs (relief-center/zone network), priority queues / binary heaps (urgency ranking), linked lists (request queues), hash tables (fast inventory lookup)
- **OOP design:** `Resource` base class with `Food`, `Medical`, `Shelter` subclasses (inheritance & polymorphism); `Volunteer` and `Request` classes; STL containers (`vector`, `map`, `priority_queue`)
- **Database:** SQLite (resource inventories, requests, allocation logs)
- **IDE:** VS Code
- **Version control:** Git / GitHub

## Project Setup / Installation


### Prerequisites
- A C++ compiler supporting C++17 or later (e.g. `g++`, `clang++`)
- SQLite3 development libraries (`libsqlite3-dev` on Debian/Ubuntu)
- CMake (recommended) or Make
- Git

### Clone the repository
```bash
git clone https://github.com/<org-or-user>/disaster-resource-allocation-system.git
cd disaster-resource-allocation-system
```

### Build
```bash
mkdir build && cd build
cmake ..
make
```

### Run
```bash
./disaster_resource_allocation
```

## System Architecture

The system is organized into four core-system modules sitting between input sources and end users:

1. **Request Manager** — validates and captures incoming relief requests, assigns priority based on urgency, and adds them to the queue.
2. **Priority Queue** — a binary heap / tree structure that dynamically re-orders requests by urgency and time.
3. **Allocation Engine** — performs graph-based matching between requests and resources (shortest path / min cost), checks resource and volunteer availability, and generates the allocation plan.
4. **Resource Database** — stores resource inventory, relief centers, volunteers, and allocation logs (backed by SQLite, plus graph, inventory, and log data).

**Inputs:** relief requests from affected zones, resource availability from centers/warehouses, location & road/zone accessibility data, volunteer availability.

**Outputs:** dispatch plan, allocation report, route plan (optimal paths), inventory status, and a performance report — consumed by relief coordinators, NGOs/agencies, government authorities, field volunteers, and citizens.

## Major Features / Modules

- **Receive and rank requests** — collects distress calls / aid requests and automatically sorts them by urgency and severity.
- **Match inventory** — identifies the closest relief center or warehouse that has the required items in stock.
- **Generate dispatch plans** — automatically produces an allocation plan per cycle showing what is being sent, where, to whom, and the suggested route.
- **Reporting** — allocation summaries/statistics, inventory status, and response-time/fulfillment performance reports.

### Deliverables
- Source code implementing the prioritization and matching logic
- Database schema (requests, inventory, warehouses, routes)
- System architecture documentation (workflow, components, data flow)
- Test scenarios with results
- Final presentation slide deck (problem, design, demo, results)

## Current Project Status / Progress

| Phase | Timeline | Task | Status |
|---|---|---|---|
| Phase I | 28/08/2026 – 12/09/2026 | Finalize requirements and system design | ✅ Complete |
| Phase II | 13/09/2026 – 30/09/2026 | Implement core data structures (graph, priority queue, hashing) and OOP class hierarchy (`Resource`, `Volunteer`, `Request`) | 🔄 In Progress |
| Phase III | 01/10/2026 – 15/10/2026 | Integrate allocation algorithm with database and build basic reporting output | ⏳ Not Started |
| Phase IV | 16/10/2026 – 31/10/2026 | Test on simulated disaster scenarios and refine allocation accuracy | ⏳ Not Started |
| Phase V | 01/11/2026 – 08/11/2026 | Final demonstration and documentation | ⏳ Not Started |

*As of the latest update, the project is in **Phase II**, actively implementing the core data structures and OOP class hierarchy.*

## Assumptions

- Relief center locations and their resource inventories are known and can be digitized.
- Requests are submitted with at least an approximate location and urgency level.
- The underlying transport network between zones can be represented as a graph with static or slowly-changing distances.

## References

1. Alem, D., Clark, A., & Moreno, A. (2016). Stochastic network models for logistics planning in disaster relief. *European Journal of Operational Research, 255*(1), 239–252.
2. Nagurney, A., & Salarpour, M. (2020). A stochastic disaster relief game theory network model. *SN Operations Research Forum, 1*(10).
3. Guigues, M., & Dufresne, J.-P. (2022). Multi-stage stochastic programming methods for adaptive disaster relief logistics planning. *Computers & Operations Research, 137*, 105473.
4. Eberhardt, K., & Mönch, L. (2025). Stochastic network optimization for strategic resource pre-positioning in disaster relief. *European Journal of Operational Research, 276*(3), 1107–1122.
5. Shehadeh, K. S., & Zografos, K. G. (2022). Stochastic optimization models for location and inventory prepositioning of relief supplies. *Computers & Industrial Engineering, 165*, 107940.

## License

*Add a license (e.g. MIT) here once decided.*