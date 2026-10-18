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

A password-protected web admin module is available at `/admin`. The public relief-request form posts to the shared server-side API, so submissions from different browsers are visible in one dashboard. Requests carry a primary resource item, quantity, and critical flag. Admin decisions consume the server-side SQLite inventory, partially fulfill critical requests when stock is short, and create a stored user notification whose exact text is also returned to the admin UI.

### Run locally

The API and static site use only Python's standard library. From the repository root:

```bash
# Create (or reset) the one admin password. Use at least 12 characters.
python3 backend/admin_server.py --set-password

# Start the web UI and API on port 8000.
python3 backend/admin_server.py
```

Open `http://localhost:8000/` for the public site and `http://localhost:8000/admin` for admin sign-in. Set initial stock in the admin dashboard's **Available inventory** panel before accepting quantified requests. The SQLite file is created at `backend/data/drras.sqlite3` and is intentionally ignored by Git. Set `DRRAS_DB_PATH=/path/to/requests.sqlite3` to select another durable location; use that same value for password setup and when starting the server. Run `python3 -m unittest discover -s backend/tests -v` for backend tests.

### Routes and protection

- `POST /api/requests` — validates and saves a pending request. Provide `itemName`, `requestedQuantity`, and optionally `isCritical` (otherwise criticality follows `severity`). The response includes the request and a per-user `notificationToken`; keep it private and send it as `X-Notification-Token` when submitting more requests from the same browser.
- `POST /api/admin/login` — verifies the configured password and issues an opaque, server-side session cookie.
- `GET /api/admin/session`, `GET /api/admin/requests`, and `GET /api/admin/inventory` — require a valid admin session.
- `POST /api/admin/inventory` with `{"itemName":"Drinking water","availableQuantity":30}` — creates or replaces the available stock for an item; requires the admin session and CSRF token.
- `PATCH /api/admin/requests/{id}` with `{"status":"accepted"}` or `{"status":"rejected","reason":"..."}` — requires the admin session and CSRF token; a request can only be reviewed once. Accepting consumes matching stock. If the requested amount exceeds stock, critical requests receive all remaining units and become `partially_approved`; non-critical requests are rejected for insufficient stock. The response contains the updated `request`, `message_to_user`, and saved `notification`.
- `GET /api/notifications` with `X-Notification-Token` — returns only that user's messages. `PATCH /api/notifications/{id}` with `{"status":"READ"}` marks one of that user's notifications as read.
- `POST /api/admin/logout` — revokes the session.

There is no end-user password/account system in the existing app, so submissions get an unguessable notification token that acts as a private capability for reading that user's messages. Only a hash of the token is stored in SQLite; the browser keeps the raw token locally. Treat it like a password and use HTTPS in deployment. Inventory in this API is separate from the browser-local Resources demo and the C++ CSV data. Existing SQLite request rows are migrated with an unspecified (zero) quantity so they remain reviewable without fabricated stock. Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes, not in the browser or source. Sessions use an `HttpOnly`, `SameSite=Strict` cookie, expire after eight hours, and admin mutations require a CSRF token. Login attempts are rate-limited. This small `http.server` implementation is a starter/demo, not a hardened public production server. Before public deployment, port the handlers to a production-grade application server (or a hardened gateway with strict request limits), use HTTPS and set `DRRAS_COOKIE_SECURE=1`, serve `/` and `/api` on the same origin, and configure backups/monitoring. A static-only host such as GitHub Pages cannot run this Python API by itself; the frontend degrades to demo mode there (see Deployment).

### Connecting request storage to the rest of the project

The checked-in project did not have a shared web database: `docs/js/storage.js` stored the browser demo data in that browser's `localStorage`, while the separate C++ console program persists records as CSV using `FileManager`. A server cannot read a visitor's `localStorage`, so the request form was wired to this SQLite-backed API; that SQLite database is now the shared source of truth for web requests and admin review. Existing browser-local records are not automatically imported, and the admin decision does not automatically dispatch resources or write into the C++ CSV files.

If you already have a server-side request database, keep the browser route contract above and replace the persistence methods in `backend/admin_server.py` (`Store.create_request_with_notification_token`, `Store.list_requests`, `Store.process_request`, and the inventory/notification methods) with calls to that database/repository. Keep the password/session/CSRF checks in the HTTP layer. If accepted requests must become operational C++ disasters, add an explicit promotion/export adapter after acceptance; do not point both stores at files that are being rewritten independently. Back up the SQLite file and restrict filesystem access to the service account.

## Deployment

The project deploys as **two independent pieces**. Decide which one you need: the console program is compiled and run by its users, and only the web module is "deployed" in the server sense.

### 1. Web app (site + request API) — needs a server, not a static host

`backend/admin_server.py` serves `docs/` **and** `/api` from one origin, so the browser's relative `fetch("/api/...")` calls resolve. It needs three things a static host cannot give it: a Python process, a writable disk for SQLite, and a persistent filesystem.

```bash
python3 backend/admin_server.py --set-password   # prompts twice, min 12 chars
python3 backend/admin_server.py                  # http://0.0.0.0:8000  (+ /admin)
```

Useful flags/env vars: `--port`, `--host`, `--db`, `--cookie-samesite`, `--cookie-partitioned`, `--allow-bearer-auth`, or `DRRAS_DB_PATH` / `DRRAS_PORT` / `PORT` / `DRRAS_COOKIE_SECURE=1` / `DRRAS_COOKIE_SAMESITE` / `DRRAS_COOKIE_PARTITIONED=1` / `DRRAS_ALLOW_BEARER_AUTH=1`. The `--set-password` step must point at the same database file you then serve, or the new server starts with no credentials and the login screen reports `No admin password is configured`.

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

GitHub Pages, Netlify, and Vercel (static mode) cannot run Python, so on those hosts the site renders and every client-side feature works — dashboard, distance ranking, allocation, Dijkstra routes, CSV export — but the public request form and the admin dashboard cannot reach a real `/api`, so they run in **demo mode** — browser-local storage and a cosmetic passphrase (see below) rather than shared, authenticated state. Pointing Pages at the wrong folder adds a second, more confusing failure: with the source path set to `/` there is no `index.html` at the repository root, and the URL answers **"There isn't a GitHub Pages site here."** even though the build reports `status: built`.

Check which one you have — a successful build with a 404 means the path, not the code:

```bash
gh api repos/<owner>/<repo>/pages --jq '.source'   # want {"branch":"main","path":"/docs"}
gh api repos/<owner>/<repo>/pages/builds?per_page=1 --jq '.[0] | {status, error: .error.message}'
```

Set it under **Settings → Pages → Build and deployment → Source: Deploy from a branch → `main` / `/docs`**, then open `https://<owner>.github.io/<repo>/`. If you cannot change that setting, the root `index.html` added here redirects into `docs/`, so `/` also serves the app; the repository-root `.nojekyll` exists so Jekyll leaves the folder alone in that configuration.

Both pages use relative asset paths, so they render correctly under the project subpath (`/<repo>/docs/...`) rather than requesting `/css/...` from the domain root and coming back unstyled.

#### Demo mode: the form and admin still work, with honest limits

`docs/js/requestService.js` probes `/api/health` on load. If a service answers, every call goes through it (shared SQLite, real authentication). If nothing answers — the Pages case — it degrades to **demo mode** instead of erroring: submissions are validated with the same rules the server uses and kept in `localStorage`, and the admin dashboard can be opened with the passphrase in `requestService.js` → `config.demoPassphrase` (default `demo-mode`). Both pages show a banner saying so. Keep that value throwaway: this file is public, so putting your real `--set-password` credential here publishes it.

Two things demo mode is not, which the code will not pretend otherwise:

- **Not access control.** The check runs in the visitor's browser, so the passphrase is readable in the page source and anyone can open the demo dashboard. It exists so a demo has a sign-in step, not to keep anyone out. Anyone who must be excluded needs the service in option 1.
- **Not shared.** `localStorage` belongs to one browser profile, so an admin on Pages sees only requests submitted from that same browser. Cross-visitor intake requires the server, by definition.

To turn the fallback off and fail loudly instead, set `config.allowDemoFallback = false`. To keep the Pages-hosted page but send data to a real service elsewhere, set `config.apiBase` to that origin — `/api/health` is then probed there, and demo mode never engages.

### 3. Console application

Not deployed at all — built per machine, and it must run *from inside* its folder so the relative `data/` CSV paths resolve:

```bash
cmake -S "Disaster Relief System" -B "Disaster Relief System/build"
cmake --build "Disaster Relief System/build"
cd "Disaster Relief System" && ./build/drras
```

Running it from the repository root instead creates an empty, stray `data/` folder there rather than reading `Disaster Relief System/data/`.

### Troubleshooting: "session expired" the instant you sign in

If the admin dashboard signs in and immediately bounces back with a session
message, the session is **not** expiring — the browser is not returning the
session cookie, and the API answers `401`, which the page reports as expiry. The
cookie defaults to `SameSite=Strict`, which is correct for a normal site but is
**withheld whenever the page is loaded inside a frame on another domain** (an IDE
preview, an `<iframe>` on the college portal). Check the server log: `POST
/api/admin/login 200` followed immediately by `GET /api/admin/requests 401` is
this exact problem, not a password or clock issue.

Two fixes, in order of preference:

1. **Open the site in its own browser tab** (top-level, not embedded). No server
   change needed, and `Strict` stays in force.
2. **If it must be embedded**, cookies may be unavailable no matter what you set —
   recent browsers block third-party cookies in cross-site frames outright, and
   Safari blocks them regardless of `SameSite`. In that case stop relying on
   cookies and let the page authenticate with a header instead:

```bash
python3 backend/admin_server.py --allow-bearer-auth
```

Sign-in then also returns a `sessionToken`, which the admin page keeps in
`sessionStorage` and sends as `Authorization: Bearer …`. It needs no cookie, so it
works inside any frame, and mutations over this path skip the CSRF token by design
(a cross-site page cannot forge that header). The cookie path is unaffected and
remains the default: without the flag the server never issues a token and
`Authorization` grants nothing. The trade-off is real — a token readable by page
script widens the XSS blast radius versus an `HttpOnly` cookie — so this is opt-in,
per-tab, and cleared on logout and on any `401`.

For a cookie-only deployment, relaxing the policy is enough:

```bash
python3 backend/admin_server.py --cookie-samesite None            # needs https
python3 backend/admin_server.py --cookie-samesite None --cookie-partitioned  # + CHIPS
```

`None` automatically adds `Secure`, and browsers then **drop the cookie on plain
http** (only `http://localhost` is exempt) — so `None` over `http://192.168.x.x`
reproduces the same 401 loop. `--cookie-partitioned` is for browsers that block
third-party cookies outright inside iframes; it is refused unless paired with
`None`. Use the same flags as env vars (`DRRAS_COOKIE_SAMESITE`,
`DRRAS_COOKIE_PARTITIONED=1`, `DRRAS_ALLOW_BEARER_AUTH=1`) for containers. Sessions
otherwise last 8 hours, so a genuine expiry after that is expected behaviour.

If a fix you deployed does not seem to take effect, suspect the cache, not the
code: the browser may serve `admin.js` straight from disk without asking. The
server answers HTML with `Cache-Control: no-cache` so entry points always
revalidate, and `docs/admin.html` references its assets as `?v=N` — bump `N` when
you change `docs/js/admin.js` or `docs/css/admin.css`, and hard-reload (Ctrl+Shift+R).

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
