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
- **C++ persistence:** CSV files through `FileManager` (the current console implementation does not link SQLite)
- **Browser demo persistence:** `localStorage` for its sample operational data
- **Admin request service:** Python 3 standard library + SQLite for shared public submissions and admin decisions
- **IDE:** VS Code
- **Version control:** Git / GitHub

## Project Setup / Installation


### Prerequisites
- A C++ compiler supporting C++17 or later (e.g. `g++`, `clang++`)
- CMake
- Git
- Python 3.9+ (only needed to run the web request/admin service; it uses the standard library and SQLite)

### Clone the repository
```bash
git clone https://github.com/debugger-ur/Disaster_resource_allocation_system.git
cd Disaster_resource_allocation_system
```

### Build
The CMake project is in `Disaster Relief System/`:
```bash
cmake -S "Disaster Relief System" -B "Disaster Relief System/build"
cmake --build "Disaster Relief System/build"
```

### Run
Run the console application with its working directory set to `Disaster Relief System/` so its relative `data/` paths resolve:
```bash
cd "Disaster Relief System"
./build/drras
```

## System Architecture

The system is organized into four core-system modules sitting between input sources and end users:

1. **Request Manager** — validates and captures incoming relief requests, assigns priority based on urgency, and adds them to the queue.
2. **Priority Queue** — a binary heap / tree structure that dynamically re-orders requests by urgency and time.
3. **Allocation Engine** — performs graph-based matching between requests and resources (shortest path / min cost), checks resource and volunteer availability, and generates the allocation plan.
4. **Persistence layers** — the C++ console program writes CSV through `FileManager`; the browser demo keeps its operational sample data in per-browser `localStorage`; the web request-review service uses SQLite as the shared store for public submissions and admin decisions.

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

## Web Admin Module: Request Review

A password-protected web admin module is available at `/admin`. The public relief-request form now posts to the same server-side API, so submissions from different browsers are visible in one dashboard. New requests start as `pending`; an admin can accept or reject them, and each decision is stored with a timestamp.

### Run locally

The API and static site use only Python's standard library. From the repository root:

```bash
# Create (or reset) the one admin password. Use at least 12 characters.
python3 backend/admin_server.py --set-password

# Start the web UI and API on port 8000.
python3 backend/admin_server.py
```

Open `http://localhost:8000/` for the public site and `http://localhost:8000/admin` for admin sign-in. The SQLite file is created at `backend/data/drras.sqlite3` and is intentionally ignored by Git. Set `DRRAS_DB_PATH=/path/to/requests.sqlite3` to select another durable location; use that same value for password setup and when starting the server. Run `python3 -m unittest discover -s backend/tests -v` for backend tests.

### Routes and protection

- `POST /api/requests` — validates and saves a public request as pending.
- `POST /api/admin/login` — verifies the configured password and issues an opaque, server-side session cookie.
- `GET /api/admin/session` and `GET /api/admin/requests` — require a valid admin session.
- `PATCH /api/admin/requests/{id}` with `{"status":"accepted"}` or `{"status":"rejected"}` — requires the admin session and a CSRF token; a request can only be reviewed once.
- `POST /api/admin/logout` — revokes the session.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes, not in the browser or source. Sessions use an `HttpOnly`, `SameSite=Strict` cookie, expire after eight hours, and admin mutations require a CSRF token. Login attempts are rate-limited. This small `http.server` implementation is a starter/demo, not a hardened public production server. Before public deployment, port the handlers to a production-grade application server (or a hardened gateway with strict request limits), use HTTPS and set `DRRAS_COOKIE_SECURE=1`, serve `/` and `/api` on the same origin, and configure backups/monitoring. A static-only host such as GitHub Pages cannot run this Python API by itself.

### Connecting request storage to the rest of the project

The checked-in project did not have a shared web database: `docs/js/storage.js` stored the browser demo data in that browser's `localStorage`, while the separate C++ console program persists records as CSV using `FileManager`. A server cannot read a visitor's `localStorage`, so the request form was wired to this SQLite-backed API; that SQLite database is now the shared source of truth for web requests and admin review. Existing browser-local records are not automatically imported, and the admin decision does not automatically dispatch resources or write into the C++ CSV files.

If you already have a server-side request database, keep the browser route contract above and replace the persistence methods in `backend/admin_server.py` (`Store.create_request`, `Store.list_requests`, and `Store.set_request_status`) with calls to that database/repository. Keep the password/session/CSRF checks in the HTTP layer. If accepted requests must become operational C++ disasters, add an explicit promotion/export adapter after acceptance; do not point both stores at files that are being rewritten independently. Back up the SQLite file and restrict filesystem access to the service account.

## Deployment

The project deploys as **two independent pieces**. Decide which one you need: the console program is compiled and run by its users, and only the web module is "deployed" in the server sense.

### 1. Web app (site + request API) — needs a server, not a static host

`backend/admin_server.py` serves `docs/` **and** `/api` from one origin, so the browser's relative `fetch("/api/...")` calls resolve. It needs three things a static host cannot give it: a Python process, a writable disk for SQLite, and a persistent filesystem.

```bash
python3 backend/admin_server.py --set-password   # prompts twice, min 12 chars
python3 backend/admin_server.py                  # http://0.0.0.0:8000  (+ /admin)
```

Useful flags/env vars: `--port`, `--host`, `--db`, or `DRRAS_DB_PATH` / `DRRAS_PORT` / `PORT` / `DRRAS_COOKIE_SECURE=1`. The `--set-password` step must point at the same database file you then serve, or the new server starts with no credentials and the login screen reports `No admin password is configured`.

**Docker (simplest reproducible deploy).** The image carries no third-party dependencies:

```bash
docker build -t drras .
docker volume create drras-data
docker run -d --name drras -p 8000:8000 -v drras-data:/data drras
docker exec -it drras python3 backend/admin_server.py --set-password   # once
```

The `-v drras-data:/data` is what keeps requests and the password alive across restarts; the container defaults `DRRAS_DB_PATH` to `/data/drras.sqlite3`. Omit the volume and a rebuild wipes the database.

**PaaS (Render / Railway / Fly.io).** Build `python3 backend/admin_server.py`, start command `python3 backend/admin_server.py`, health check path `/api/health`. The platform injects `PORT` and the app binds to it. These hosts have **ephemeral** filesystems: you must attach a persistent disk mounted at `/data` (and set `DRRAS_DB_PATH=/data/drras.sqlite3`), or every deploy/restart discards submitted requests.

**VM/VPS with systemd.** Put the SQLite file on the service account's own path and front it with nginx/Caddy for HTTPS:

```ini
# /etc/systemd/system/drras.service
[Service]
Environment=DRRAS_DB_PATH=/var/lib/drras/drras.sqlite3
Environment=DRRAS_COOKIE_SECURE=1
Environment=DRRAS_PORT=8000
ExecStart=/usr/bin/python3 /srv/drras/backend/admin_server.py
Restart=always
[Install]
WantedBy=multi-user.target
```

`DRRAS_COOKIE_SECURE=1` must only be set when TLS terminates in front of the app, otherwise the browser drops the session cookie and you can never sign in. Run `mkdir -p /var/lib/drras` and back that file up; it is the whole web datastore.

### 2. Static-only host (GitHub Pages) — dashboard works, submissions do not

GitHub Pages, Netlify, and Vercel (static mode) cannot run Python, so on those hosts the site renders and every client-side feature works — dashboard, distance ranking, allocation, Dijkstra routes, CSV export — but **submitting a relief request and the admin dashboard report `Could not reach the request service`**, because there is no `/api`. The checked-in `docs/.nojekyll` plus Pages serving the `docs/` folder is exactly this configuration.

If you choose it: **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`**, then open `https://<user>.github.io/<repo>/`. Both pages now use relative asset paths, so they render correctly under the project subpath. Do not expect the form to work there; point the form at a separately hosted instance of option 1 instead, or keep the demo local.

### 3. Console application

Not deployed at all — built per machine, and it must run *from inside* its folder so the relative `data/` CSV paths resolve:

```bash
cmake -S "Disaster Relief System" -B "Disaster Relief System/build"
cmake --build "Disaster Relief System/build"
cd "Disaster Relief System" && ./build/drras
```

Running it from the repository root instead creates an empty, stray `data/` folder there rather than reading `Disaster Relief System/data/`.

### Pre-public checklist

- Change the demo password; 12+ characters, and never commit it or the `.sqlite3` file (`backend/data/` is git-ignored).
- Serve over HTTPS and set `DRRAS_COOKIE_SECURE=1`.
- This is a stdlib `http.server`-based demo: single-process, no proxy trust — the `X-Forwarded-For` rate limiter trusts whatever the client sends unless a reverse gateway overwrites it, so put nginx/Caddy in front and rate-limit there too. Do not expose the port directly.
- Keep `/` and `/api` same-origin (the client uses relative URLs and `credentials: "same-origin"`).
- Back up the SQLite file; schedule it, don't rely on the host's disk.
- Accepted requests are recorded only in SQLite — they do not auto-dispatch resources or write into the C++ CSVs.

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
