export const seedDisasters = [
  { id: "D101", type: "FLOOD", severity: "HIGH", affectedPeople: 120, requiredResources: ["Ambulance", "Supply"], locationName: "Rishikesh", latitude: 30.0869, longitude: 78.2676 },
  { id: "D102", type: "FLOOD", severity: "CRITICAL", affectedPeople: 250, requiredResources: ["Ambulance", "MedicalTeam", "Supply"], locationName: "Dehradun", latitude: 30.3165, longitude: 78.0322 },
  { id: "D103", type: "EARTHQUAKE", severity: "MEDIUM", affectedPeople: 60, requiredResources: ["RescueTeam", "Equipment"], locationName: "Haridwar", latitude: 29.9457, longitude: 78.1642 },
];

export const seedResources = [
  { id: "R101", category: "Ambulance", type: "ALS", quantity: 1, latitude: 30.3255, longitude: 78.0431, locationName: "Dehradun", priority: 1, contact: "+91-9000000001" },
  { id: "R102", category: "RescueTeam", type: "Flood Rescue", quantity: 10, latitude: 30.0869, longitude: 78.2676, locationName: "Rishikesh", priority: 1, contact: "+91-9000000002" },
  { id: "R103", category: "MedicalTeam", type: "Trauma Team", quantity: 5, latitude: 30.3165, longitude: 78.0400, locationName: "Dehradun", priority: 1, contact: "+91-9000000003" },
  { id: "R104", category: "Ambulance", type: "BLS", quantity: 1, latitude: 29.9457, longitude: 78.1642, locationName: "Haridwar", priority: 2, contact: "+91-9000000004" },
  { id: "R105", category: "Supply", type: "Food", quantity: 500, latitude: 30.0869, longitude: 78.2676, locationName: "Rishikesh", priority: 3, contact: "N/A" },
  { id: "R106", category: "Supply", type: "Water", quantity: 1000, latitude: 29.9457, longitude: 78.1642, locationName: "Haridwar", priority: 3, contact: "N/A" },
  { id: "R107", category: "Equipment", type: "HeavyMachinery", quantity: 2, latitude: 30.3165, longitude: 78.0500, locationName: "Dehradun", priority: 2, contact: "+91-9000000007" },
  { id: "R108", category: "Ambulance", type: "ALS", quantity: 1, latitude: 30.4500, longitude: 77.9000, locationName: "Mussoorie", priority: 2, contact: "+91-9000000008" },
  { id: "R109", category: "RescueTeam", type: "Earthquake Rescue", quantity: 8, latitude: 29.9450, longitude: 78.1700, locationName: "Haridwar", priority: 1, contact: "+91-9000000009" },
];

export const seedHospitals = [
  { id: "H01", name: "Dehradun City Hospital", latitude: 30.3200, longitude: 78.0350, totalBeds: 200, availableBeds: 45, emergencyCapacity: 20 },
  { id: "H04", name: "Rishikesh General Hospital", latitude: 30.0870, longitude: 78.2680, totalBeds: 120, availableBeds: 30, emergencyCapacity: 15 },
  { id: "H07", name: "Haridwar Medical Center", latitude: 29.9450, longitude: 78.1650, totalBeds: 150, availableBeds: 60, emergencyCapacity: 25 },
];

export const seedShelters = [
  { id: "S01", name: "Dehradun Community Shelter", latitude: 30.3100, longitude: 78.0400, capacity: 500, occupied: 120 },
  { id: "S02", name: "Rishikesh Relief Camp", latitude: 30.0900, longitude: 78.2700, capacity: 300, occupied: 80 },
  { id: "S03", name: "Haridwar Shelter Home", latitude: 29.9500, longitude: 78.1700, capacity: 400, occupied: 200 },
];
