# DRRAS — Disaster Relief Resource Allocation System

A working web application for the full relief-request lifecycle: a citizen reports
an emergency, the server verifies it (duplicate detection + explainable risk
scoring), a coordinator reviews it in a command centre, and the nearest suitable
help centre is chosen using **live road distance and travel time** — not a
straight line. Every decision, dispatch and configuration change is audited.

The repository also contains the original C++17 console program used for the
course project; it is independent of the web service and described at the end.

---

## Quick start

Requirements: **Python 3.10+** (standard library only) and a modern browser.
Node.js is not required at runtime.

```bash
git clone https://github.com/debugger-ur/Disaster_resource_allocation_system.git
cd Disaster_resource_allocation_system

# 1. Create the admin password (12+ characters, prompted twice).
python3 backend/admin_server.py --set-password

# 2. (Optional) Insert realistic demo data: 19 help centres + 9 sample requests.
python3 backend/admin_server.py --seed-demo

# 3. Start the site and API on port 8000.
python3 backend/admin_server.py
```

Open:

- **Public site** — <http://localhost:8000/>
- **Command centre** — <http://localhost:8000/admin> (sign in with the password)

The SQLite database is created at `backend/data/drras.sqlite3` (ignored by Git).
Use `--db /path/to/file.sqlite3` or `DRRAS_DB_PATH` consistently for password
setup, seeding and serving. Demo data can also be inserted later from
**Admin → Settings → Demo data**.

> If the sign-in screen says no password is configured, run `--set-password`
> against the same database file the server uses.

### Preview/embedded frames

If the app is shown inside a sandboxed iframe (for example an IDE preview),
cookies may be blocked. Start the server with `--allow-bearer-auth` and the
browser will fall back to a short-lived bearer token stored in `sessionStorage`:

```bash
python3 backend/admin_server.py --allow-bearer-auth
```

---

## What is implemented

### Public site (`/`)

- **Overview** — live counts, active incidents, recent dispatches, and a Leaflet
  map with category-coded markers.
- **Report an emergency** — disaster type, severity, affected people, resource
  quantities, description, evidence upload (JPEG/PNG/PDF), location by map pin,
  place search (Nominatim through the server), or GPS **only after the button is
  pressed**. Submitting returns a receipt with a request ID.
- **Nearby help** — centre list beside the map with category, radius,
  stocked-with-resource and “open only” filters, availability, stock, road
  distance, ETA, contact, and route drawing. Selecting a disaster shows centres nearest to it.
- **Track a request** — timeline, status, allocations and coordinator messages.
  Recent IDs are remembered in `localStorage` on that device only.
- **How it works** — plain-language explanation of verification and allocation.

### Command centre (`/admin`)

- **Overview** — requests submitted, awaiting verification, approved, rejected,
  possible duplicates, high-risk, active disasters, available vs committed
  resources, risk distribution, centre network map, recent audit.
- **Verification queue** — tabs for all, high-risk, duplicate review, manual
  review and auto-approval, with search, severity filter and sorting.
- **All requests** — filter by status, risk, severity, type; search and sort.
- **Request drawer** — full detail, risk score with the exact points that made
  it, every duplicate match and its factor breakdown, evidence, reporter
  contact, status timeline and audit trail.
- **Actions** — approve, reject (reason required), request more information,
  flag, merge duplicate, link related report, keep separate, start response,
  resolve.
- **Allocation** — nearest-centre recommendations with routed distance/ETA,
  coverage, availability, load balancing, per-centre stock, multi-centre plan,
  quantity confirmation, override reason, and dispatch/deliver/cancel tracking.
- **Centres & stock** — searchable inventory; administrators can add or edit
  centres and stock.
- **Audit log** — who, when, what, and why, append-only.
- **Settings** (administrators) — auto-approval rules, duplicate/risk
  thresholds, rate limits, central reserve, routing status, demo seed.
  Operators can review and allocate but cannot change configuration.

---

## How verification works

Every submission is validated server-side, then compared with recent reports.
Nothing in this pipeline can reject a request — automation may only route work
to a person.

**Duplicate detection** compares the new report with reports from the last
72 hours (configurable) using:

| Signal | Why it matters |
|---|---|
| Location proximity | Scores fall off with distance; only reports within 50 km are compared |
| Disaster category | Same category scores higher than a related one |
| Description similarity | Token overlap of the two descriptions |
| Submission time | Recent reports score higher inside the window |
| Contact details | Same normalised phone/email |
| Requested resources | Overlap in requested resource categories |

If the combined score reaches the configurable threshold (default 60), the
request becomes **Possible duplicate** and both IDs, locations, distance and
factor points are shown. A coordinator must **merge**, **link** or **keep
separate** it; it is never rejected automatically.

**Risk scoring** produces 0–100 plus named reasons and a full checklist:

- thin or missing description, invalid/missing phone or email;
- repeated submissions from the same contact or a burst from one IP;
- inconsistent or far-apart locations for the same contact;
- conflicting details (for example CRITICAL with ≤1 affected person);
- reused evidence (byte-identical file already uploaded on another request);
- duplicate signal.

Thresholds map the score to **Low / Medium / High** (defaults 25 / 55) and are
configurable. The score and each contributing factor are visible in the admin
drawer, together with checks that passed.

**Routing and queues**

| Outcome | Status | Queue |
|---|---|---|
| Possible duplicate | `possible_duplicate` | duplicate review |
| High risk | `under_verification` | high-risk verification |
| Medium risk | `awaiting_approval` | manual review |
| Low risk, rules not met | `awaiting_approval` | manual review |
| Low risk, all rules met | `approved` | auto-approval |

Auto-approval is **off by default**. When enabled it can only approve: it
requires low risk below a ceiling that must stay under the medium threshold, an
allowed severity, a minimum description length, valid contact, and no duplicate
block. Any failure simply sends the request to a person.

Workflow statuses: `submitted → under_verification / possible_duplicate →
awaiting_approval → approved → resources_assigned → in_progress → resolved`,
with `rejected` available only as an explicit human decision.

---

## Allocation, maps and routing

- Recommendations rank centres on **stock coverage, road distance, availability
  and current load**, weighted by severity. Closed centres are excluded from the
  proposed plan, and no centre is asked for more than it holds.
- Multi-centre plans show the split and what remains uncovered.
- The actual allocation is a database transaction: stock is decremented exactly
  once, over-allocation is refused, and cancelling returns stock to the centre.
- Dispatch, delivery and cancellation notify the reporter in-app and appear in
  the request timeline and audit log.
- Distances and ETAs come from **OSRM** through a server-side proxy; place search
  uses **Nominatim**. If either service is unreachable, the API returns
  `distanceSource: "estimate"`, the UI labels it as an estimate, and **no route
  line is drawn**. The browser never receives a third-party key.
- Leaflet 1.9.4 is vendored in `docs/vendor/leaflet/`; map tiles come directly
  from OpenStreetMap in the browser.

---

## Sample data vs. live functionality

| Area | State |
|---|---|
| Reporting, validation, verification, queue, approvals, actions | Working, persisted in SQLite |
| Auth, roles (admin/operator), CSRF, rate limiting, audit | Working |
| Allocation, stock deduction, dispatch/delivery lifecycle | Working |
| 19 help centres around Dehradun | **Sample seed data** (`--seed-demo` / Settings) |
| 9 demo requests incl. duplicate pair and high-risk record | **Sample seed data**, marked “Demo data” |
| OSRM road routing and Nominatim search | Working when the deployment has outbound internet |
| OSM map tiles | Need network in the browser |
| Offline/no-routing mode | Working, but shows labelled estimates and no route line |
| Email/SMS notifications | **Not implemented** — notifications are in-app |
| Production web server / TLS | Deploy behind nginx or Caddy; the stdlib server is not a hardened edge |

Demo data is never mixed silently into live data: seeded requests carry
`isDemo`, and the admin UI labels them.

---

## Architecture

```
Browser (vanilla ES modules + vendored Leaflet)
  docs/index.html, docs/admin.html, docs/js/*.js, docs/css/*.css
        │  same-origin fetch, cookie or bearer session + CSRF token
        ▼
Python standard-library HTTP server  backend/admin_server.py
  validation, auth, RBAC, routes, static files, upload limits
        │
        ├── backend/db_store.py          SQLite schema, workflow, allocation, audit
        ├── backend/drras_verification.py duplicate + risk engines (pure)
        ├── backend/drras_allocation.py   scoring and multi-centre plan (pure)
        ├── backend/drras_geo.py          OSRM / Nominatim proxy with cache + fallback
        ├── backend/drras_seed.py         sample centres and demo requests
        └── backend/drras_common.py       constants, defaults, helpers
```

### Files that changed or were added in this redesign

- `backend/admin_server.py` — rewritten HTTP layer: public and admin routes,
  validation, RBAC, CSRF, rate limiting, uploads, static serving.
- `backend/db_store.py` — new storage/domain layer and schema v2 with migration.
- `backend/drras_common.py`, `drras_verification.py`, `drras_allocation.py`,
  `drras_geo.py`, `drras_seed.py` — new modules.
- `backend/tests/test_admin_server.py` — extended API suite;
  `test_verification.py`, `test_allocation.py`, `test_db_store.py` — new
  engine/store suites.
- `docs/index.html`, `docs/admin.html`, `docs/css/style.css`,
  `docs/css/admin.css` — redesigned public site and command centre.
- `docs/js/api.js`, `format.js`, `map.js`, `shared.js`, `main.js`, `admin.js` —
  new front-end modules. The previous localStorage demo modules
  (`requestService.js`, `seedData.js`, managers, `distanceCalculator.js`, etc.)
  were removed; nothing references them.
- `docs/vendor/leaflet/` — vendored Leaflet 1.9.4 (no CDN dependency).
- `README.md`, `Dockerfile` — updated for the new app.

---

## API

Public:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Service status (also reports whether a password exists) |
| `GET` | `/api/overview` | Public statistics, active incidents, recent dispatches |
| `GET` | `/api/help-centres` | Full centre directory |
| `GET` | `/api/nearby?lat=&lon=&category=&radius=&availability=&limit=` | Nearest centres with distances/ETA |
| `GET` | `/api/places?q=` | Place search through the server proxy |
| `GET` | `/api/route?fromLat=&fromLon=&toLat=&toLon=` | Road route (or labelled estimate) |
| `GET` | `/api/inventory` | Central reserve levels |
| `POST` | `/api/requests` | Submit a report |
| `GET` | `/api/requests/{id}` | Track a report (no other reporter's private data) |
| `POST` | `/api/uploads` | Upload evidence as base64 with type/size checks |

Admin (session required; mutations also require `X-CSRF-Token`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/admin/login`, `/api/admin/logout` | Sign in / out |
| `GET` | `/api/admin/session` | Session, CSRF token, role |
| `GET` | `/api/admin/requests`, `/api/admin/requests/{id}` | List / detail |
| `POST` | `/api/admin/requests/{id}/action` | approve, reject, request_info, flag, merge, link, keep_separate, start, resolve |
| `GET` | `/api/admin/requests/{id}/recommendations` | Ranked centres + plan |
| `POST` | `/api/admin/requests/{id}/allocations` | Commit stock from a centre |
| `PATCH` | `/api/admin/allocations/{id}` | assigned / dispatched / delivered / cancelled |
| `GET/PUT` | `/api/admin/settings` | Approval rules and thresholds |
| `GET/PUT` | `/api/admin/inventory` | Central reserve |
| `GET/POST` | `/api/admin/help-centres`; `PATCH /{id}` | Centre directory and stock |
| `GET` | `/api/admin/stats` | Dashboard counters |
| `GET` | `/api/admin/audit?limit=&requestId=` | Audit entries |
| `GET` | `/api/admin/notifications`, `/api/admin/allocations` | Operational feeds |
| `POST` | `/api/admin/seed-demo` | Insert sample data once |
| `GET` | `/api/admin/evidence/{id}` | Fetch private uploaded evidence |

The legacy `PATCH /api/admin/requests/{id}` with `{"status": "accepted" | "rejected"}`
is still accepted for existing integrations.

---

## Security and reliability

- Passwords: PBKDF2-HMAC-SHA256 with per-user salt; never in source or browser.
- Sessions: opaque server-side tokens, `HttpOnly`, `SameSite=Strict` by default,
  eight-hour expiry, logout revocation, optional bearer mode for framed previews.
- CSRF token required for every admin mutation; login attempts rate-limited.
- Role-based access: `admin` can configure; `operator` can review, allocate and
  dispatch but cannot change settings or centres.
- Server-side validation for all submission, allocation, centre and settings
  payloads, including coherent risk thresholds and quantity caps.
- Uploads: MIME allow-list (JPEG/PNG/PDF), 5 MB cap, generated filenames,
  private serving route, magic-byte signature check.
- SQLite foreign keys and transactions prevent stock going negative or the same
  allocation being counted twice; cancelling restores stock exactly once.
- Submission rate limiting per IP (loopback exempt for local development).
- All errors return JSON and the UI shows loading, empty and failure states.
- Private reporter contact details are only available to authenticated admins.

For public deployment, terminate TLS at a reverse proxy, set
`DRRAS_COOKIE_SECURE=1`, back up the SQLite file, and keep the service account’s
filesystem access narrow.

---

## Configuration

| Variable / flag | Default | Meaning |
|---|---|---|
| `DRRAS_DB_PATH` / `--db` | `backend/data/drras.sqlite3` | SQLite location |
| `DRRAS_UPLOAD_DIR` | `<db dir>/uploads` | Evidence storage |
| `DRRAS_HOST` / `--host` | `0.0.0.0` | Bind address |
| `DRRAS_PORT` / `--port` / `PORT` | `8000` | Port |
| `DRRAS_ROUTING_URL` | `https://router.project-osrm.org` | OSRM base URL |
| `DRRAS_GEOCODING_URL` | `https://nominatim.openstreetmap.org` | Nominatim base URL |
| `DRRAS_ROUTING_TIMEOUT` | `4` | Seconds before falling back to an estimate |
| `DRRAS_OFFLINE=1` | off | Skip all outbound routing/geocoding calls |
| `DRRAS_COOKIE_SECURE=1` | off | Send cookies over HTTPS only |
| `DRRAS_COOKIE_SAMESITE` / `--cookie-samesite` | `Strict` | Cookie policy |
| `DRRAS_ALLOW_BEARER_AUTH=1` / `--allow-bearer-auth` | off | Return a bearer token on login |
| `DRRAS_ADMIN_PASSWORD`, `DRRAS_OPERATOR_PASSWORD` | — | Bootstrap passwords if none stored (12+ chars) |

Settings stored in the database (admin UI): auto-approval on/off and ceiling,
allowed severities, minimum description length, contact requirement, duplicate
block, duplicate window/threshold, medium/high risk thresholds, submission rate
limit and window.

---

## Tests

```bash
python3 -m unittest discover -s backend/tests -v
```

149 tests cover the HTTP API (auth, CSRF, RBAC, validation, rate limits,
uploads), verification engines, allocation scoring, SQLite workflow, stock
transactions, merge/link, audit and demo seeding. Set `DRRAS_OFFLINE=1` for
deterministic tests without outbound routing calls.

---

## Deployment

The app serves `docs/` and `/api` from one origin, so it needs a Python process
and a writable persistent disk — a static-only host cannot run it.

**Docker**

```bash
docker build -t drras .
docker volume create drras-data
docker run -d --name drras -p 8000:8000 -v drras-data:/data drras
docker exec -it drras python3 backend/admin_server.py --set-password
```

The image sets `DRRAS_DB_PATH=/data/drras.sqlite3`; the named volume keeps the
database and password across restarts. Without it, every rebuild starts empty.

**PaaS (Render/Railway/Fly.io)** — build and start
`python3 backend/admin_server.py`, health check `/api/health`, and attach a
persistent disk at `/data` with `DRRAS_DB_PATH=/data/drras.sqlite3`. Set
`DRRAS_COOKIE_SECURE=1` when served over HTTPS.

**VM with systemd** — run behind nginx/Caddy for TLS, set
`DRRAS_DB_PATH=/var/lib/drras/drras.sqlite3`, and keep the unit’s user as the
only owner of that directory.

---

## Known limitations

- Email/SMS delivery is not implemented; notifications appear in the tracker and
  command centre.
- This is a standard-library HTTP server intended for a course/demo deployment.
  Use a reverse proxy and process supervision for real traffic.
- Routing/geocoding depend on public OSRM/Nominatim instances; heavy use should
  self-host them or use a provider with an appropriate usage policy.
- The web app and the C++ console program share concepts but not a database; no
  automatic export from web allocations into the console CSV files.

---

## Original C++ console program

`Disaster Relief System/` is the C++17 coursework implementation (graphs, priority
queue, hash tables, CSV persistence). It remains runnable and unchanged:

```bash
cmake -S "Disaster Relief System" -B "Disaster Relief System/build"
cmake --build "Disaster Relief System/build"
cd "Disaster Relief System" && ./build/drras
```

It is a separate console application and does not serve the website.

---

## Team

**Team DSCPP-III-2026-T100** — Semester 3

| Role | Name | Student ID | Section |
|---|---|---|---|
| Team Lead | Shubham Bisht | 2510012245 | F |
| Member | Samiksha Bhandari | 2510010580 | DS1 |
| Member | Sarthak Semwal | 2510010180 | ML4 |
| Member | Nikhil Singh Rawat | 2510012376 | DS2 |

Built for *DS in C & OOPs with C++ (DSCPP-III-2026-T100)*.
