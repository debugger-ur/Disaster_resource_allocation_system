"""Road distance, travel time and place search.

Road distances come from a real routing engine (OSRM by default) through a
server-side proxy, so no API key or third-party origin ever reaches the
browser. When the routing service cannot be reached the module returns a
clearly labelled *estimate* (great-circle distance scaled by a road factor) and
``source: "estimate"``; the UI renders that differently from a routed result and
never draws a route line for it.

Configuration (environment):
    DRRAS_ROUTING_URL     default https://router.project-osrm.org
    DRRAS_GEOCODING_URL   default https://nominatim.openstreetmap.org
    DRRAS_ROUTING_TIMEOUT seconds, default 4
    DRRAS_OFFLINE=1       skip outbound calls entirely (tests, air-gapped demos)
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from drras_verification import PLACE_GAZETTEER, haversine_km

ROUTING_URL = os.environ.get("DRRAS_ROUTING_URL", "https://router.project-osrm.org").rstrip("/")
GEOCODING_URL = os.environ.get("DRRAS_GEOCODING_URL", "https://nominatim.openstreetmap.org").rstrip("/")
ROUTING_TIMEOUT = float(os.environ.get("DRRAS_ROUTING_TIMEOUT", "4"))
OFFLINE = os.environ.get("DRRAS_OFFLINE", "") == "1"
USER_AGENT = "DRRAS/2.0 (disaster resource allocation; academic project)"
# Average urban/suburban road speed used only for labelled estimates.
ESTIMATE_SPEED_KMH = 30.0
ESTIMATE_ROAD_FACTOR = 1.34

_TABLE_CACHE: dict[str, tuple[float, object]] = {}
_ROUTE_CACHE: dict[str, tuple[float, object]] = {}
_GEOCODE_CACHE: dict[str, tuple[float, object]] = {}
TABLE_TTL = 60 * 30
ROUTE_TTL = 60 * 30
GEOCODE_TTL = 60 * 60 * 6
NEGATIVE_TTL = 60 * 5


def _cache_get(cache: dict, key: str):
    entry = cache.get(key)
    if not entry:
        return None
    expires, value = entry
    if expires < time.time():
        cache.pop(key, None)
        return None
    return value


def _cache_put(cache: dict, key: str, value, ttl: float) -> None:
    if len(cache) > 500:
        cache.clear()
    cache[key] = (time.time() + ttl, value)


def _fetch_json(url: str, timeout: float) -> object | None:
    if OFFLINE:
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def estimate_leg(origin: tuple[float, float], destination: tuple[float, float]) -> dict:
    """Labelled road estimate used when no routing engine answers."""
    straight = haversine_km(origin[0], origin[1], destination[0], destination[1])
    distance = straight * ESTIMATE_ROAD_FACTOR
    minutes = (distance / ESTIMATE_SPEED_KMH) * 60 if distance > 0 else 0
    return {
        "distanceKm": round(distance, 2),
        "durationMin": max(1, round(minutes)) if distance > 0.05 else 0,
        "straightLineKm": round(straight, 2),
        "source": "estimate",
        "provider": "estimate",
        "note": "Estimated road distance from straight-line distance; live routing was unavailable.",
    }


def _coord_key(points: list[tuple[float, float]]) -> str:
    return ";".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points)


def route_legs(origin: tuple[float, float], destinations: list[tuple[float, float]]) -> list[dict]:
    """Road distance/time for one origin to many destinations.

    Uses OSRM's table service in a single call. Falls back to labelled estimates
    if the service is unreachable, slow, or returns malformed data.
    """
    if not destinations:
        return []
    capped = destinations[:24]
    key = _coord_key([origin, *capped])
    cached = _cache_get(_TABLE_CACHE, key)
    if isinstance(cached, list) and len(cached) == len(capped):
        return cached

    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in [origin, *capped])
    url = f"{ROUTING_URL}/table/v1/driving/{coords}?annotations=distance,duration"
    payload = _fetch_json(url, ROUTING_TIMEOUT)
    legs: list[dict] = []
    if isinstance(payload, dict) and payload.get("code") == "Ok":
        distances = payload.get("distances") or []
        durations = payload.get("durations") or []
        if len(distances) >= 1 and len(distances[0]) >= len(capped):
            for index in range(len(capped)):
                try:
                    meters = distances[0][index + 1]
                    seconds = durations[0][index + 1]
                except (IndexError, TypeError):
                    meters, seconds = None, None
                if meters is None or seconds is None:
                    legs.append(estimate_leg(origin, capped[index]))
                    continue
                straight = haversine_km(origin[0], origin[1], capped[index][0], capped[index][1])
                legs.append({
                    "distanceKm": round(float(meters) / 1000, 2),
                    "durationMin": max(1, round(float(seconds) / 60)),
                    "straightLineKm": round(straight, 2),
                    "source": "osrm",
                    "provider": "osrm",
                    "note": None,
                })
            _cache_put(_TABLE_CACHE, key, legs, TABLE_TTL)
            return legs

    _cache_put(_TABLE_CACHE, key, None, NEGATIVE_TTL)
    return [estimate_leg(origin, point) for point in capped]


def geocode(query: str, known_places: list[dict] | None = None) -> list[dict]:
    """Place search through Nominatim with an offline/local fallback.

    ``known_places`` lets the caller mix in help-centre names and active reports,
    so search remains useful even without internet access.
    """
    text = str(query or "").strip()
    if len(text) < 2:
        return []
    key = text.lower()
    cached = _cache_get(_GEOCODE_CACHE, key)
    if isinstance(cached, list):
        return cached

    results: list[dict] = []
    url = (
        f"{GEOCODING_URL}/search?format=jsonv2&limit=6&countrycodes=in&addressdetails=0"
        f"&q={urllib.parse.quote(text)}"
    )
    payload = _fetch_json(url, ROUTING_TIMEOUT)
    if isinstance(payload, list):
        for item in payload:
            try:
                results.append({
                    "name": item.get("display_name") or text,
                    "shortName": (item.get("name") or item.get("display_name") or text).split(",")[0],
                    "latitude": float(item["lat"]),
                    "longitude": float(item["lon"]),
                    "source": "nominatim",
                })
            except (KeyError, TypeError, ValueError):
                continue

    lowered = key
    for place, (lat, lon) in PLACE_GAZETTEER.items():
        if lowered in place or place in lowered:
            results.append({
                "name": place.title() + ", Uttarakhand",
                "shortName": place.title(),
                "latitude": lat,
                "longitude": lon,
                "source": "local",
            })
    for place in known_places or []:
        name = str(place.get("name") or "")
        if lowered and lowered in name.lower():
            try:
                results.append({
                    "name": name,
                    "shortName": name,
                    "category": place.get("category"),
                    "latitude": float(place["latitude"]),
                    "longitude": float(place["longitude"]),
                    "source": "local",
                })
            except (KeyError, TypeError, ValueError):
                continue

    # De-duplicate by rounded coordinates, keep the first (live) result.
    seen = set()
    unique = []
    for item in results:
        marker = (round(item["latitude"], 4), round(item["longitude"], 4))
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    unique = unique[:8]
    _cache_put(_GEOCODE_CACHE, key, unique, GEOCODE_TTL if unique else NEGATIVE_TTL)
    return unique


def route_geometry(origin: tuple[float, float], destination: tuple[float, float]) -> dict | None:
    """Route geometry for the selected centre, or ``None`` if routing is down."""
    key = _coord_key([origin, destination])
    cached = _cache_get(_ROUTE_CACHE, key)
    if isinstance(cached, dict):
        return cached
    coords = f"{origin[1]:.6f},{origin[0]:.6f};{destination[1]:.6f},{destination[0]:.6f}"
    url = f"{ROUTING_URL}/route/v1/driving/{coords}?overview=full&geometries=geojson&steps=false"
    payload = _fetch_json(url, ROUTING_TIMEOUT)
    if isinstance(payload, dict) and payload.get("code") == "Ok" and payload.get("routes"):
        route = payload["routes"][0]
        geometry = route.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        result = {
            "geometry": [[float(lat), float(lon)] for lon, lat in coordinates],
            "distanceKm": round(float(route.get("distance", 0)) / 1000, 2),
            "durationMin": max(1, round(float(route.get("duration", 0)) / 60)),
            "source": "osrm",
            "provider": "osrm",
        }
        _cache_put(_ROUTE_CACHE, key, result, ROUTE_TTL)
        return result
    _cache_put(_ROUTE_CACHE, key, None, NEGATIVE_TTL)
    return None


def distance_only(origin: tuple[float, float], destination: tuple[float, float]) -> dict:
    """Cheap great-circle helper (not used as a road distance)."""
    straight = haversine_km(origin[0], origin[1], destination[0], destination[1])
    return {"straightLineKm": round(straight, 2)}


def bearing_label(origin: tuple[float, float], destination: tuple[float, float]) -> str:
    """Compass direction, handy in the nearby list ("2.4 km north-east")."""
    lat1, lon1, lat2, lon2 = map(math.radians, [origin[0], origin[1], destination[0], destination[1]])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    degrees = (math.degrees(math.atan2(x, y)) + 360) % 360
    labels = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return labels[int((degrees + 22.5) // 45) % 8]


def routing_status() -> dict:
    return {
        "provider": "osrm" if not OFFLINE else "offline",
        "routingUrl": ROUTING_URL,
        "geocodingUrl": GEOCODING_URL,
        "offline": OFFLINE,
        "timeoutSeconds": ROUTING_TIMEOUT,
        "note": (
            "Road distances and travel times come from OSRM through this server. "
            "If it is unreachable, distances are labelled as estimates."
        ),
    }
