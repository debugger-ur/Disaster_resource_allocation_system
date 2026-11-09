"""Road routing and place search with honest offline fallbacks.

OSRM supplies real road distance and travel time. Nominatim supplies place
search. Both are called from the server, never from the browser. If a service
is unreachable, the API labels the result as an estimate and the interface says
so instead of pretending it is live data.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from rules import haversine_km

ROUTING_URL = os.environ.get("DRRAS_ROUTING_URL", "https://router.project-osrm.org").rstrip("/")
GEOCODING_URL = os.environ.get("DRRAS_GEOCODING_URL", "https://nominatim.openstreetmap.org").rstrip("/")
TIMEOUT = float(os.environ.get("DRRAS_ROUTING_TIMEOUT", "4"))
USER_AGENT = "DRRAS-BTech-Project/3.0 (college project; contact: student)"
ESTIMATE_SPEED_KMH = 30.0
ESTIMATE_ROAD_FACTOR = 1.34
CACHE: dict[str, tuple[float, object]] = {}
CACHE_TTL = 30 * 60

# A few local names keep search useful when Nominatim is unavailable.
PLACES = {
    "dehradun": (30.3165, 78.0322),
    "doon": (30.3165, 78.0322),
    "raipur": (30.3050, 78.1000),
    "clement town": (30.2660, 78.0100),
    "rajpur": (30.3500, 78.0700),
    "mussoorie": (30.4598, 78.0644),
    "rishikesh": (30.0869, 78.2676),
    "haridwar": (29.9457, 78.1642),
    "doiwala": (30.1900, 78.1210),
    "vikasnagar": (30.4100, 77.7800),
    "selaqui": (30.1150, 78.0750),
    "chakrata": (30.7000, 77.8600),
}


def is_offline() -> bool:
    return os.environ.get("DRRAS_OFFLINE", "") == "1"


def _cache_get(key: str):
    entry = CACHE.get(key)
    if not entry:
        return None
    expires, value = entry
    if expires < time.time():
        CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: object, ttl: int = CACHE_TTL) -> None:
    if len(CACHE) > 400:
        CACHE.clear()
    CACHE[key] = (time.time() + ttl, value)


def _fetch_json(url: str):
    if is_offline():
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def estimate_leg(origin: tuple[float, float], destination: tuple[float, float]) -> dict:
    straight = haversine_km(origin[0], origin[1], destination[0], destination[1])
    distance = straight * ESTIMATE_ROAD_FACTOR
    minutes = round((distance / ESTIMATE_SPEED_KMH) * 60) if distance > 0.05 else 0
    return {
        "distanceKm": round(distance, 2),
        "durationMin": max(1, minutes) if distance > 0.05 else 0,
        "straightLineKm": round(straight, 2),
        "source": "estimate",
        "note": "Road routing was unavailable; distance is estimated from the straight line.",
    }


def road_legs(origin: tuple[float, float], destinations: list[tuple[float, float]]) -> list[dict]:
    """Road distance/time from one origin to many centres using OSRM's table API."""
    if not destinations:
        return []
    capped = destinations[:24]
    key = "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in [origin, *capped])
    cached = _cache_get(key)
    if isinstance(cached, list) and len(cached) == len(capped):
        return cached

    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in [origin, *capped])
    payload = _fetch_json(f"{ROUTING_URL}/table/v1/driving/{coords}?annotations=distance,duration")
    legs = []
    try:
        distances = payload["distances"][0]
        durations = payload["durations"][0]
        if payload.get("code") != "Ok" or len(distances) < len(capped) + 1:
            raise ValueError
    except (TypeError, KeyError, ValueError, IndexError):
        legs = [estimate_leg(origin, point) for point in capped]
        _cache_put(key, legs, 5 * 60)
        return legs

    for index, point in enumerate(capped):
        meters, seconds = distances[index + 1], durations[index + 1]
        if meters is None or seconds is None:
            legs.append(estimate_leg(origin, point))
            continue
        legs.append({
            "distanceKm": round(float(meters) / 1000, 2),
            "durationMin": max(1, round(float(seconds) / 60)),
            "straightLineKm": round(haversine_km(origin[0], origin[1], point[0], point[1]), 2),
            "source": "osrm",
            "note": None,
        })
    _cache_put(key, legs)
    return legs


def route_between(origin: tuple[float, float], destination: tuple[float, float]) -> dict:
    """Road geometry and ETA for the selected centre."""
    key = "route|" + "|".join(f"{p[0]:.5f},{p[1]:.5f}" for p in (origin, destination))
    cached = _cache_get(key)
    if isinstance(cached, dict):
        return cached

    coords = f"{origin[1]:.6f},{origin[0]:.6f};{destination[1]:.6f},{destination[0]:.6f}"
    payload = _fetch_json(
        f"{ROUTING_URL}/route/v1/driving/{coords}?overview=full&geometries=geojson"
    )
    try:
        route = payload["routes"][0]
        geometry = [[float(lat), float(lon)] for lon, lat in route["geometry"]["coordinates"]]
        result = {
            "geometry": geometry,
            "distanceKm": round(float(route["distance"]) / 1000, 2),
            "durationMin": max(1, round(float(route["duration"]) / 60)),
            "source": "osrm",
            "note": None,
        }
    except (TypeError, KeyError, IndexError, ValueError):
        leg = estimate_leg(origin, destination)
        result = {
            "geometry": None,
            "distanceKm": leg["distanceKm"],
            "durationMin": leg["durationMin"],
            "source": "estimate",
            "note": leg["note"],
        }
    _cache_put(key, result)
    return result


def search_places(query: str, centres: list[dict]) -> list[dict]:
    """Search Nominatim, then add matching local centres and known places."""
    text = str(query or "").strip()
    if len(text) < 2:
        return []
    key = "geocode|" + text.lower()
    cached = _cache_get(key)
    if isinstance(cached, list):
        return cached

    results = []
    url = (
        f"{GEOCODING_URL}/search?format=jsonv2&limit=5&countrycodes=in"
        f"&q={urllib.parse.quote(text)}"
    )
    payload = _fetch_json(url)
    if isinstance(payload, list):
        for item in payload:
            try:
                results.append({
                    "name": item.get("display_name") or text,
                    "latitude": float(item["lat"]),
                    "longitude": float(item["lon"]),
                    "source": "nominatim",
                })
            except (KeyError, TypeError, ValueError):
                continue

    lowered = text.lower()
    for name, (lat, lon) in PLACES.items():
        if lowered in name:
            results.append({
                "name": name.title() + ", Uttarakhand",
                "latitude": lat,
                "longitude": lon,
                "source": "local",
            })
    for centre in centres:
        if lowered in str(centre.get("name", "")).lower():
            results.append({
                "name": centre["name"],
                "latitude": centre["latitude"],
                "longitude": centre["longitude"],
                "source": "centre",
            })

    unique, seen = [], set()
    for item in results:
        marker = (round(item["latitude"], 4), round(item["longitude"], 4))
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    unique = unique[:7]
    _cache_put(key, unique)
    return unique


def routing_status() -> dict:
    return {
        "provider": "offline" if is_offline() else "OSRM",
        "offline": is_offline(),
        "note": (
            "Road distance and travel time come from OSRM. If it is unreachable, "
            "distances are labelled as estimates."
        ),
    }
