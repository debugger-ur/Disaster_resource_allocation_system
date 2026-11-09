"""Sample help-centre data for the Dehradun area.

These records are realistic examples for a college demonstration, not an
authoritative emergency directory. Replace the phone numbers and verify the
locations before using the system for anything real.
"""

CENTRES = [
    {
        "id": "HC-DDN-01", "name": "Doon District Hospital", "category": "hospital",
        "address": "Hospital Road, Dehradun", "latitude": 30.3185, "longitude": 78.0340,
        "phone": "+91 135 240 0101", "availability": "available",
        "notes": "24x7 emergency and trauma unit",
        "stock": {"Medicine": 120, "MedicalTeam": 3, "Food": 60, "Water": 100},
    },
    {
        "id": "HC-DDN-02", "name": "Shri Mahant Indiresh Hospital", "category": "hospital",
        "address": "Patel Nagar, Dehradun", "latitude": 30.3018, "longitude": 78.0270,
        "phone": "+91 135 240 0202", "availability": "limited",
        "notes": "Emergency beds limited; ICU nearly full",
        "stock": {"Medicine": 70, "MedicalTeam": 2, "Water": 40},
    },
    {
        "id": "HC-DDN-03", "name": "Himalayan Hospital, Jolly Grant", "category": "hospital",
        "address": "Jolly Grant, Dehradun", "latitude": 30.1775, "longitude": 78.1580,
        "phone": "+91 135 240 0303", "availability": "available",
        "notes": "Level-1 trauma centre",
        "stock": {"Medicine": 90, "MedicalTeam": 2, "Shelter": 20},
    },
    {
        "id": "HC-DDN-10", "name": "Raipur Relief Camp", "category": "relief_camp",
        "address": "Raipur, Dehradun", "latitude": 30.3050, "longitude": 78.1000,
        "phone": "+91 135 240 1010", "availability": "available",
        "notes": "Cots for 300 people; community kitchen running",
        "stock": {"Food": 400, "Water": 500, "Shelter": 60, "RescueTeam": 2},
    },
    {
        "id": "HC-DDN-11", "name": "Clement Town Relief Camp", "category": "relief_camp",
        "address": "Clement Town, Dehradun", "latitude": 30.2652, "longitude": 78.0098,
        "phone": "+91 135 240 1111", "availability": "limited",
        "notes": "Nearly full; overflow at Raipur camp",
        "stock": {"Food": 150, "Water": 120, "Shelter": 15},
    },
    {
        "id": "HC-DDN-20", "name": "Dehradun Food & Water Hub", "category": "food_water",
        "address": "Race Course, Dehradun", "latitude": 30.3245, "longitude": 78.0445,
        "phone": "+91 135 240 2020", "availability": "available",
        "notes": "Hot meals and potable water, 06:00-22:00",
        "stock": {"Food": 600, "Water": 900, "Other": 50},
    },
    {
        "id": "HC-RSH-21", "name": "Rishikesh Food & Water Point", "category": "food_water",
        "address": "Muni Ki Reti, Rishikesh", "latitude": 30.0910, "longitude": 78.2700,
        "phone": "+91 135 240 2121", "availability": "available",
        "notes": "Water tankers and dry ration packets",
        "stock": {"Food": 300, "Water": 450},
    },
    {
        "id": "HC-DDN-30", "name": "NDRF Rescue Base, Dehradun", "category": "rescue_team",
        "address": "Sahastradhara Road, Dehradun", "latitude": 30.2900, "longitude": 78.0560,
        "phone": "+91 135 240 3030", "availability": "available",
        "notes": "Two flood-rescue squads on standby",
        "stock": {"RescueTeam": 8, "Other": 25},
    },
    {
        "id": "HC-DDN-31", "name": "SDRF Rescue Unit, Rajpur", "category": "rescue_team",
        "address": "Rajpur Road, Dehradun", "latitude": 30.3350, "longitude": 78.0620,
        "phone": "+91 135 240 3131", "availability": "limited",
        "notes": "Rope rescue and swift-water team",
        "stock": {"RescueTeam": 4, "MedicalTeam": 1},
    },
    {
        "id": "HC-DDN-40", "name": "State Emergency Warehouse", "category": "warehouse",
        "address": "Dehradun Industrial Area", "latitude": 30.2735, "longitude": 78.0290,
        "phone": "+91 135 240 4040", "availability": "available",
        "notes": "Primary buffer stock for the district",
        "stock": {"Food": 900, "Water": 1000, "Shelter": 200, "Medicine": 200, "Other": 100},
    },
    {
        "id": "HC-RSH-50", "name": "Tapovan Shelter", "category": "shelter",
        "address": "Tapovan, Rishikesh", "latitude": 30.0995, "longitude": 78.3000,
        "phone": "+91 135 240 5050", "availability": "available",
        "notes": "60 beds; family rooms available",
        "stock": {"Shelter": 70, "Food": 80, "Water": 100},
    },
    {
        "id": "HC-DDN-51", "name": "Doiwala Shelter", "category": "shelter",
        "address": "Doiwala, Dehradun", "latitude": 30.1880, "longitude": 78.1200,
        "phone": "+91 135 240 5151", "availability": "available",
        "notes": "80 beds with accessible facilities",
        "stock": {"Shelter": 90, "Food": 120, "Water": 150},
    },
    {
        "id": "HC-DDN-60", "name": "Raipur Medical Camp", "category": "medical_camp",
        "address": "Raipur, Dehradun", "latitude": 30.3070, "longitude": 78.0940,
        "phone": "+91 135 240 6060", "availability": "limited",
        "notes": "Doctors 08:00-20:00; minor injuries and fever",
        "stock": {"Medicine": 60, "MedicalTeam": 2, "Water": 80},
    },
]


def demo_requests() -> list[dict]:
    """Four clearly labelled reports used to demonstrate the workflow."""
    return [
        {
            "id": "REQ-DEMO-1001", "type": "FLOOD", "severity": "HIGH",
            "people": 45, "description": (
                "Flood water has entered the lanes near Raipur canal. Around 45 people "
                "are sheltering in the community hall and need food, drinking water and medicines."
            ),
            "location_name": "Raipur canal area, Dehradun", "latitude": 30.3041,
            "longitude": 78.0972, "contact_name": "Meera Devi",
            "contact_phone": "9876543210", "contact_email": "",
            "resources": {"Food": 45, "Water": 90, "Medicine": 20},
            "status": "approved", "queue": "auto_approval", "risk": 5, "risk_level": "low",
            "auto": 1, "demo": 1,
        },
        {
            "id": "REQ-DEMO-1002", "type": "FLOOD", "severity": "HIGH",
            "people": 40, "description": (
                "Water is rising near the Raipur canal. About 40 families are in the "
                "community hall and we urgently need food packets and drinking water."
            ),
            "location_name": "Raipur, Dehradun", "latitude": 30.3052,
            "longitude": 78.0985, "contact_name": "Ramesh Kumar",
            "contact_phone": "9876500011", "contact_email": "",
            "resources": {"Food": 40, "Water": 80},
            "status": "pending", "queue": "duplicate_review", "risk": 30, "risk_level": "medium",
            "auto": 0, "demo": 1,
        },
        {
            "id": "REQ-DEMO-1003", "type": "LANDSLIDE", "severity": "CRITICAL",
            "people": 12, "description": (
                "A landslide has blocked the road near Vikasnagar. Twelve people are "
                "trapped near the bus stop and a rescue team is needed immediately."
            ),
            "location_name": "Vikasnagar bus stop, Dehradun", "latitude": 30.4080,
            "longitude": 77.7810, "contact_name": "Anil Rawat",
            "contact_phone": "9812345678", "contact_email": "anil@example.com",
            "resources": {"RescueTeam": 2, "MedicalTeam": 1, "Medicine": 10},
            "status": "assigned", "queue": "manual_review", "risk": 20, "risk_level": "low",
            "auto": 0, "demo": 1,
        },
        {
            "id": "REQ-DEMO-1004", "type": "FIRE", "severity": "MEDIUM",
            "people": 8, "description": (
                "A shop fire was controlled by the fire brigade in Clement Town. "
                "The family needs temporary shelter and water for the night."
            ),
            "location_name": "Clement Town market, Dehradun", "latitude": 30.2670,
            "longitude": 78.0110, "contact_name": "Sunita Negi",
            "contact_phone": "9765432109", "contact_email": "",
            "resources": {"Shelter": 8, "Water": 20},
            "status": "resolved", "queue": "manual_review", "risk": 10, "risk_level": "low",
            "auto": 0, "demo": 1,
        },
    ]
