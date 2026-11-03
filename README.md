# DRRAS — Disaster Resource Allocation System

A BTech PBL project that manages a relief request from citizen report to resource
dispatch. It is deliberately small: Python standard library, SQLite, vanilla
JavaScript and Leaflet — no framework, no build step and no npm runtime.

**Public site:** `/` · **Admin dashboard:** `/admin`

## What it does

**Citizen side**
- Register or sign in; anonymous reports are also accepted.
- Report a disaster with type, severity, location, description, resource quantities and an optional photo/PDF.
- Pick a location by map click, place search or GPS.
- Track a request by ID and see the decision/dispatch timeline.
- See all reports linked to the signed-in account.

**Admin side**
- View every request, with filters for status, review queue and risk.
- Approve, reject, request more information, start a response and resolve.
- See the exact duplicate matches, distance, score and reasons.
- See risk points and the contact details of the reporter.
- Manage help centres, availability and stock.
- Compare recommended centres by stock coverage, road distance, travel time and availability.
- Assign resources, dispatch, mark delivered or cancel an allocation.
- Configure safe auto-approval and duplicate thresholds.

## Verification logic

Every report is validated on the server. It is then compared with reports from the
last 72 hours (configurable) using:

| Signal | Weight |
|---|---:|
| Location within 50 km | up to 30 |
| Disaster category | 25 (12 for a related category) |
| Description similarity | up to 30 |
| Submission time | up to 15 |

A score above the threshold creates a **duplicate warning**, never an automatic
rejection. The administrator sees the matching request ID and each factor.

Risk scoring adds named flags for a short description, missing contact details,
an outside-area coordinate, repeated contact activity and a strong duplicate
match. Auto-approval is **off by default** and can only approve when every safe
condition configured by the administrator passes. Every other report goes to a
person.

## Technology and structure

```text
Browser (HTML, CSS, vanilla ES modules, vendored Leaflet)
   │ same-origin JSON, session cookie or preview bearer token, CSRF header
   ▼
backend/app.py        HTTP server, routes, auth, uploads, static files
backend/db.py         SQLite schema, workflow, stock transactions, audit
backend/rules.py      duplicate detection, risk scoring and auto-approval rules
backend/allocation.py nearest-centre scoring
backend/geo.py        OSRM routing and Nominatim search with estimate fallback
backend/seed.py       sample help centres and demo requests
backend/config.py     constants, validation and settings defaults
docs/                 public page, admin page, CSS, JavaScript and Leaflet
```

There are **22 focused tests** covering authentication, CSRF, validation,
duplicate warnings, auto-approval, ownership, uploads, allocation, stock return,
centre management and nearby filtering.

```bash
DRRAS_OFFLINE=1 python3 -m unittest discover -s backend/tests -v
```

`DRRAS_OFFLINE=1` makes tests deterministic and avoids outbound routing requests.

**Project size:** 3,992 lines of application code (comments, blank lines and the
vendored Leaflet library excluded). The backend, frontend and tests together are
5,261 physical lines — below the 6,000-line target for this rewrite.

## Run locally

Requirements: **Python 3.10+** and a modern browser.

```bash
# 1. Set the admin password (12+ characters, prompted twice).
python3 backend/app.py --set-password

# 2. Optional: insert four labelled demo reports and 13 sample centres.
python3 backend/app.py --seed-demo

# 3. Start the site and API.
python3 backend/app.py
```

Open <http://localhost:8000/> and <http://localhost:8000/admin>.

The database defaults to `backend/data/drras.sqlite3`. Demo data can also be
inserted from **Admin → Settings → Insert / reset sample data**.

The bundled command `--allow-bearer-auth` enables a token fallback for embedded
previews where cookies are blocked. It is not needed on a normal deployment.

## Configuration

| Variable | Purpose |
|---|---|
| `DRRAS_ADMIN_PASSWORD` | Bootstraps the admin password on the first start (12+ chars). Ignored once a password exists. |
| `DRRAS_DB_PATH` | SQLite file path (default `backend/data/drras.sqlite3`). |
| `DRRAS_COOKIE_SECURE=1` | Send the session cookie only over HTTPS. |
| `DRRAS_ALLOWED_ORIGIN` | Optional single allowed CORS origin for a separately hosted frontend. |
| `DRRAS_ROUTING_URL` | OSRM base URL (default public OSRM). |
| `DRRAS_GEOCODING_URL` | Nominatim base URL. |
| `DRRAS_OFFLINE=1` | Skip outbound routing/geocoding calls. |
| `DRRAS_ALLOW_BEARER_AUTH=1` | Allow bearer-token sessions in addition to cookies. |
| `PORT` | Injected by Render; the app binds to it automatically. |

There is **no default admin password**. A salted PBKDF2 hash is stored in SQLite;
the password can only be replaced, not recovered. To replace it, point the command
at the same database the server uses:

```bash
python3 backend/app.py --db /path/to/drras.sqlite3 --set-password
```

## Deploy on Render

The repository includes a root `render.yaml` using the Docker runtime and a
health check at `/api/health`.

1. Create a **New Blueprint** from the repository, or create a Web Service manually.
2. Set `DRRAS_ADMIN_PASSWORD` (12+ characters) before the first deploy.
3. Set `DRRAS_COOKIE_SECURE=1`.
4. Leave `PORT` unset — Render provides it.
5. Health check path: `/api/health`.

**Free plan:** the filesystem is ephemeral, so reports and the admin password
reset on every redeploy. Re-set the password through `DRRAS_ADMIN_PASSWORD` and
reseed demo data from the admin dashboard. This is documented rather than hidden.

**Paid plan:** attach a disk at `/data` and set
`DRRAS_DB_PATH=/data/drras.sqlite3`. Uploads are stored in `/data/uploads`
automatically. The commented block in `render.yaml` shows the exact configuration.

Manual settings if you do not use the Blueprint:

- Runtime: Docker
- Build command: not required (the Dockerfile handles it)
- Start command: `python3 backend/app.py`
- Health check: `/api/health`

No `requirements.txt` is needed because the application uses only the standard
library. The backend serves the frontend, so ordinary use is same-origin and does
not need permissive CORS.

## Honest limitations

- Help-centre names, phones and stock are **sample data**. They must be verified
  before any real use and are labelled “sample” in the admin dashboard.
- Road distances and ETAs come from public OSRM. If it is unavailable, the UI
  labels the distance as an estimate and does not draw a route line.
- Map tiles require browser internet access; Leaflet itself is vendored.
- Email and SMS notifications are not implemented. Status changes are visible in
  the tracking timeline.
- The Python HTTP server is suitable for a college demonstration, not a hardened
  public emergency service.
- The web app does not share a database with the C++ console program.

## Original C++ program

`Disaster Relief System/` is the original C++17 console application and remains
untouched. It demonstrates OOP, graphs, a priority queue, hash maps and CSV
persistence.

```bash
cmake -S "Disaster Relief System" -B "Disaster Relief System/build"
cmake --build "Disaster Relief System/build"
cd "Disaster Relief System" && ./build/drras
```

## Team

**Team DSCPP-III-2026-T100** — Semester 3

| Role | Name | Student ID | Section |
|---|---|---|---|
| Team Lead | Shubham Bisht | 2510012245 | F |
| Member | Samiksha Bhandari | 2510010580 | DS1 |
| Member | Sarthak Semwal | 2510010180 | ML4 |
| Member | Nikhil Singh Rawat | 2510012376 | DS2 |

Built for *DS in C & OOPs with C++ (DSCPP-III-2026-T100)*.
