export class Entity {
  constructor(id, latitude, longitude) {
    if (!id) throw new Error("ID is required.");
    if (latitude < -90 || latitude > 90) throw new Error("Latitude must be between -90 and 90.");
    if (longitude < -180 || longitude > 180) throw new Error("Longitude must be between -180 and 180.");
    this.id = id;
    this.latitude = Number(latitude);
    this.longitude = Number(longitude);
  }
}

export const SeverityWeight = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };

export class Disaster extends Entity {
  constructor({ id, type, severity, affectedPeople, requiredResources, locationName, latitude, longitude, timestamp, status }) {
    super(id, latitude, longitude);
    if (affectedPeople < 0) throw new Error("Affected people cannot be negative.");
    this.type = type;
    this.severity = severity;
    this.affectedPeople = Number(affectedPeople);
    this.requiredResources = requiredResources || [];
    this.locationName = locationName;
    this.timestamp = timestamp || new Date().toLocaleString();
    this.status = status || "ACTIVE";
  }
  get priorityScore() {
    return SeverityWeight[this.severity] * 1_000_000 + this.affectedPeople;
  }
}

export class Resource extends Entity {
  constructor({ id, category, type, quantity, status, latitude, longitude, locationName, priority, contact }) {
    super(id, latitude, longitude);
    if (quantity < 0) throw new Error("Quantity cannot be negative.");
    if (priority < 1 || priority > 5) throw new Error("Priority must be between 1 and 5.");
    this.category = category;
    this.type = type;
    this.quantity = Number(quantity);
    this.status = status || "AVAILABLE";
    this.locationName = locationName;
    this.priority = Number(priority);
    this.contact = contact || "N/A";
  }
}

export class Hospital extends Entity {
  constructor({ id, name, latitude, longitude, totalBeds, availableBeds, emergencyCapacity, status }) {
    super(id, latitude, longitude);
    if (Number(availableBeds) > Number(totalBeds)) throw new Error("Available beds cannot exceed total beds.");
    this.name = name;
    this.totalBeds = Number(totalBeds);
    this.availableBeds = Number(availableBeds);
    this.emergencyCapacity = Number(emergencyCapacity);
    this.status = status || "OPERATIONAL";
  }
}

export class Shelter extends Entity {
  constructor({ id, name, latitude, longitude, capacity, occupied }) {
    super(id, latitude, longitude);
    if (Number(occupied) > Number(capacity)) throw new Error("Occupied cannot exceed capacity.");
    this.name = name;
    this.capacity = Number(capacity);
    this.occupied = Number(occupied);
  }
  get availableCapacity() { return this.capacity - this.occupied; }
}

export class Allocation {
  constructor({ allocationId, disasterId, resourceId, resourceCategory, distanceKm, timestamp, status }) {
    this.allocationId = allocationId;
    this.disasterId = disasterId;
    this.resourceId = resourceId;
    this.resourceCategory = resourceCategory;
    this.distanceKm = Number(distanceKm);
    this.timestamp = timestamp || new Date().toLocaleString();
    this.status = status || "DISPATCHED";
  }
}
