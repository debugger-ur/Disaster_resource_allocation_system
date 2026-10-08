// Dedicated distance module — mirrors C++ DistanceCalculator class.
export const EARTH_RADIUS_KM = 6371.0;

export function haversineDistanceKm(lat1, lon1, lat2, lon2) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const rLat1 = toRad(lat1);
  const rLat2 = toRad(lat2);

  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rLat1) * Math.cos(rLat2) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return EARTH_RADIUS_KM * c;
}

export function sortByDistance(items, lat, lon) {
  return items
    .map((item) => ({
      item,
      distance: haversineDistanceKm(lat, lon, item.latitude, item.longitude),
    }))
    .sort((a, b) => a.distance - b.distance);
}

export function findNearest(items, lat, lon) {
  if (!items.length) return null;
  return sortByDistance(items, lat, lon)[0];
}
