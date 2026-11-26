"""
scripts/init_enstudio_db.py — Initializes the `Enstudio` database in MongoDB
with structured enterprise plant asset inventory (Plants, Units, Areas, Systems,
Subsystems, Instruments, Accessories, and Tie-In Points) for the Brownfield Agent.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pymongo
from dotenv import load_dotenv

# Ensure studio is on path
STUDIO_DIR = Path(__file__).resolve().parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

# Load .env
load_dotenv(STUDIO_DIR / ".env")

# No hardcoded fallback — see adapters/mongodb.py for why the previous
# baked-in connection string (username + password + cluster host) was removed.
# This seeder WRITES to the database, so running it against a default cluster
# nobody configured is especially undesirable.
MONGO_URI = (os.getenv("MONGODB_URI") or "").strip()
if not MONGO_URI:
    raise SystemExit(
        "MONGODB_URI is not set. Copy mongo.env.example to mongo.env and set "
        "MONGODB_URI before running this seeder. There is deliberately no "
        "built-in default."
    )
DB_NAME = os.getenv("MONGODB_DATABASE", "Enstudio")

ASSET_INVENTORY_SEED = [
    # ── AREA 100: FEED PRE-TREATMENT & INGRESS SYSTEM ─────────────────────────
    {
        "asset_id": "AST-100-001",
        "tag_number": "TP-01",
        "asset_name": "Feed Supply Header Tie-In Nozzle",
        "asset_type": "Tie-In Point",
        "category": "Tie-In / Spec Break",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Supply Header"
        },
        "specifications": {
            "tag_number": "TP-01",
            "line_size": "4 inch",
            "piping_spec": "4''-PG-2001-A1B",
            "flange_rating": "Class 300 RF",
            "material": "Carbon Steel A106-B",
            "design_pressure": "25.0 barg",
            "design_temperature": "120 °C",
            "operating_pressure": "16.0 barg"
        },
        "connected_system": {
            "name": "Main Plant Feed Battery Limit",
            "type": "Piping Header"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-100-002",
        "tag_number": "HV-101A",
        "asset_name": "Pressure Tap Root Isolation Valve",
        "asset_type": "Isolation Valve",
        "category": "Root Valve",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Pressure Sensing Branch"
        },
        "specifications": {
            "tag_number": "HV-101A",
            "manufacturer": "Swagelok",
            "model": "SS-4P4T Needle Valve",
            "body_material": "316 Stainless Steel",
            "connection_size": "1/2 inch NPT",
            "pressure_rating": "Class 6000",
            "location": "Header PG-2001 Tap 01"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-100-003",
        "tag_number": "SYP-101",
        "asset_name": "Pigtail Condensation Siphon",
        "asset_type": "Siphon Loop",
        "category": "Pigtail Siphon",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Pressure Sensing Branch"
        },
        "specifications": {
            "tag_number": "SYP-101",
            "manufacturer": "Swagelok",
            "model": "1/2'' Sch 80 Pigtail Siphon",
            "material": "Seamless 316 SS"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-100-004",
        "tag_number": "MNF-101",
        "asset_name": "Coplanar 3-Valve Manifold",
        "asset_type": "Manifold",
        "category": "3-Valve Manifold",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Pressure Sensing Branch"
        },
        "specifications": {
            "tag_number": "MNF-101",
            "manufacturer": "Anderson Greenwood / Emerson",
            "model": "305 Coplanar 3-Valve Manifold",
            "material": "316L Stainless Steel",
            "mounting": "Direct Mount to PT-101"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-100-005",
        "tag_number": "PT-101",
        "asset_name": "Feed Ingress Pressure Transmitter",
        "asset_type": "Pressure Transmitter",
        "category": "Pressure Transmitter",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Pressure Control Loop"
        },
        "specifications": {
            "tag_number": "PT-101",
            "manufacturer": "Emerson Rosemount",
            "model": "3051S Coplanar Pressure Transmitter",
            "serial_number": "SN-EM-882104",
            "calibrated_range": "0.0 - 16.0 bar",
            "protocol": "4-20mA HART 7",
            "connected_system": "Cabinet PNL-100 / Rack 01 / Slot 01 / Channel AI-01",
            "location": "Unit 100 - Feed Ingress Station"
        },
        "instrument_config": {
            "hart_identity": {
                "equipment_category": "Pressure Transmitter",
                "hart_tag": "PT-101",
                "hart_long_tag": "FEED_INGRESS_PRESSURE",
                "descriptor": "Feed Ingress Line Pressure",
                "message": "Calibrated annually per ISA-5.1"
            },
            "pv_mapping": {
                "primary_variable": "Pressure",
                "secondary_variable": "Sensor Temperature",
                "urv": "16.0",
                "lrv": "0.0",
                "pv_units": "bar"
            },
            "measurement_control": {
                "damping": "0.5 s",
                "flow_direction": "Forward Only"
            }
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-100-006",
        "tag_number": "V-101",
        "asset_name": "Feed Surge Drum",
        "asset_type": "Pressure Vessel",
        "category": "Process Vessel",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Surge & Degassing Unit"
        },
        "specifications": {
            "tag_number": "V-101",
            "manufacturer": "Belleli Energy",
            "design_code": "ASME Sec VIII Div 1",
            "material": "Carbon Steel SA-516 Gr 70",
            "volume_m3": 45.0,
            "design_pressure": "22.0 barg",
            "design_temperature": "150 °C"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-100-007",
        "tag_number": "P-101A",
        "asset_name": "Primary Feed Booster Pump (Duty)",
        "asset_type": "Centrifugal Pump",
        "category": "Process Pump",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Motive Pumping Station"
        },
        "specifications": {
            "tag_number": "P-101A",
            "manufacturer": "Goulds Pumps / ITT",
            "model": "Model 3196 ANSI Process Pump",
            "capacity": "65 m3/h",
            "head": "85 m",
            "motor_power": "45 kW",
            "sparing": "Duty (100%)"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-100-008",
        "tag_number": "P-101B",
        "asset_name": "Standby Feed Booster Pump (Standby)",
        "asset_type": "Centrifugal Pump",
        "category": "Process Pump",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100 - Feed Pretreatment",
            "system": "Hydrocarbon Ingress & Blending System",
            "subsystem": "Feed Motive Pumping Station"
        },
        "specifications": {
            "tag_number": "P-101B",
            "manufacturer": "Goulds Pumps / ITT",
            "model": "Model 3196 ANSI Process Pump",
            "capacity": "65 m3/h",
            "head": "85 m",
            "motor_power": "45 kW",
            "sparing": "Standby (100%)"
        },
        "status": "operating"
    },

    # ── AREA 200: REACTION CORE & THERMAL SUB-SYSTEM ──────────────────────────
    {
        "asset_id": "AST-200-001",
        "tag_number": "R-201",
        "asset_name": "Catalytic Hydrotreating Reactor",
        "asset_type": "Chemical Reactor",
        "category": "Chemical Reactor",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Catalytic Reaction & Hydrogen Addition System",
            "subsystem": "Packed Bed Reactor Station"
        },
        "specifications": {
            "tag_number": "R-201",
            "manufacturer": "Mangiarotti SpA",
            "design_code": "ASME Section VIII Div 2",
            "material": "2.25Cr-1Mo-V Clad with SS 347",
            "design_pressure": "45.0 barg",
            "design_temperature": "420 °C",
            "operating_pressure": "32.0 barg",
            "operating_temperature": "360 °C"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-200-002",
        "tag_number": "E-201",
        "asset_name": "Feed / Effluent Combined Heat Exchanger",
        "asset_type": "Heat Exchanger",
        "category": "Heat Exchanger",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Catalytic Reaction & Hydrogen Addition System",
            "subsystem": "Heat Recovery & Preheating Station"
        },
        "specifications": {
            "tag_number": "E-201",
            "manufacturer": "Alfa Laval / Olmi",
            "type": "TEMA AES Shell & Tube",
            "duty_kw": 3200,
            "shell_material": "Carbon Steel",
            "tube_material": "SS 321"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-200-003",
        "tag_number": "TT-2041",
        "asset_name": "Reactor Bed Multi-Point Temperature Transmitter",
        "asset_type": "Temperature Transmitter",
        "category": "Temperature Transmitter",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Catalytic Reaction & Hydrogen Addition System",
            "subsystem": "Reactor Temperature Monitoring"
        },
        "specifications": {
            "tag_number": "TT-2041",
            "manufacturer": "Emerson Rosemount",
            "model": "3144P Temperature Transmitter with 114C TW",
            "serial_number": "SN-EM-994102",
            "calibrated_range": "0.0 - 450.0 °C",
            "protocol": "4-20mA HART 7",
            "connected_system": "Cabinet PNL-100 / Rack 02 / Slot 04 / Channel AI-02"
        },
        "instrument_config": {
            "hart_identity": {
                "equipment_category": "Temperature Transmitter",
                "hart_tag": "TT-2041",
                "hart_long_tag": "REACTOR_BED_TEMPERATURE",
                "descriptor": "Reactor Bed Profile Temp"
            },
            "pv_mapping": {
                "primary_variable": "Temperature",
                "urv": "450.0",
                "lrv": "0.0",
                "pv_units": "°C"
            }
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-200-004",
        "tag_number": "PSV-2041",
        "asset_name": "Reactor Shell Safety Relief Valve",
        "asset_type": "Relief Valve",
        "category": "Safety Relief Valve",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Overpressure Protection & Safety Relief System",
            "subsystem": "High Pressure Flare Rail"
        },
        "specifications": {
            "tag_number": "PSV-2041",
            "manufacturer": "Crosby / Emerson",
            "model": "JOS-E Spring Loaded Safety Valve",
            "orifice": "2 x 3 H",
            "set_pressure": "40.0 barg",
            "design_code": "API 520 / API 526",
            "discharge_to": "FLARE-HDR"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-200-005",
        "tag_number": "POS-2041",
        "asset_name": "Smart Valve Positioner",
        "asset_type": "Positioner",
        "category": "Smart Valve Positioner",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Catalytic Reaction & Hydrogen Addition System",
            "subsystem": "Reactor Feed Control Loop"
        },
        "specifications": {
            "tag_number": "POS-2041",
            "manufacturer": "Fisher",
            "model": "FIELDVUE DVC6200 Digital Valve Controller",
            "calibrated_range": "4 - 20 mA Input / 0 - 100 % Travel",
            "protocol": "4-20mA HART 7",
            "connected_system": "Cabinet PNL-100 / Rack 02 / Slot 05 / Channel AO-01"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-200-006",
        "tag_number": "ACT-2041",
        "asset_name": "Pneumatic Diaphragm Actuator",
        "asset_type": "Actuator",
        "category": "Pneumatic Actuator",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Catalytic Reaction & Hydrogen Addition System",
            "subsystem": "Reactor Feed Control Loop"
        },
        "specifications": {
            "tag_number": "ACT-2041",
            "manufacturer": "Fisher",
            "model": "Fisher 667 Direct-Acting Diaphragm Actuator",
            "bench_set": "3 - 15 psi Operating Air",
            "fail_action": "Fail Closed (Air-to-Open)"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-200-007",
        "tag_number": "PCV-2041",
        "asset_name": "Reactor Feed Pressure Control Valve",
        "asset_type": "Control Valve",
        "category": "Control Valve",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Catalytic Reaction & Hydrogen Addition System",
            "subsystem": "Reactor Feed Control Loop"
        },
        "specifications": {
            "tag_number": "PCV-2041",
            "manufacturer": "Fisher Controls",
            "model": "ET Globe Control Valve Class 600 RF",
            "serial_number": "SN-FSH-77192",
            "body_size": "4 inch",
            "trim_material": "Stellite Faced 316 SS",
            "calibrated_range": "0 - 100 % Travel",
            "connected_system": "Cabinet PNL-100 / Rack 02 / Slot 05 / Channel AO-01"
        },
        "status": "operating"
    },
    {
        "asset_id": "AST-200-008",
        "tag_number": "TP-02",
        "asset_name": "Effluent Return Header Tie-In Nozzle",
        "asset_type": "Tie-In Point",
        "category": "Tie-In / Spec Break",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200 - Reaction Core",
            "system": "Effluent Transfer & Product Recovery System",
            "subsystem": "Effluent Return Header"
        },
        "specifications": {
            "tag_number": "TP-02",
            "line_size": "4 inch",
            "piping_spec": "4''-PG-2002-A1B",
            "flange_rating": "Class 300 RF",
            "material": "Carbon Steel A106-B",
            "operating_pressure": "14.5 barg"
        },
        "connected_system": {
            "name": "Downstream Separation Battery Limit",
            "type": "Piping Header"
        },
        "status": "operating"
    },

    # ── AREA 300: DCS & CONTROL MARSHALLING ──────────────────────────────────
    {
        "asset_id": "AST-300-001",
        "tag_number": "Cabinet PNL-100",
        "asset_name": "Main DCS Marshalling Cabinet PNL-100",
        "asset_type": "DCS Cabinet",
        "category": "Control Cabinet",
        "location": {
            "site": "Houston Petrochemical Complex",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-300 - Control Building Rack Room",
            "system": "DCS Automation & Safety System",
            "subsystem": "Marshalling Rack Cabinet"
        },
        "specifications": {
            "tag_number": "Cabinet PNL-100",
            "manufacturer": "Emerson Process Management",
            "system_type": "DeltaV Distributed Control System",
            "protocol": "4-20mA HART 7 & Foundation Fieldbus",
            "available_ai_channels": 16,
            "available_ao_channels": 8,
            "power_supply": "24 VDC Redundant"
        },
        "status": "operating"
    }
]


def seed_enstudio_database():
    print(f"Connecting to MongoDB: {MONGO_URI[:60]}...")
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    db = client[DB_NAME]
    
    # 1. Seed assets collection
    assets_col = db["assets"]
    print(f"Clearing old records in {DB_NAME}.assets...")
    assets_col.delete_many({})
    
    print(f"Inserting {len(ASSET_INVENTORY_SEED)} physical assets into {DB_NAME}.assets...")
    res = assets_col.insert_many(ASSET_INVENTORY_SEED)
    print(f"Successfully inserted {len(res.inserted_ids)} assets into {DB_NAME}.assets!")
    
    # 2. Seed systems collection
    systems_col = db["systems"]
    systems_col.delete_many({})
    systems_data = [
        {
            "system_id": "SYS-100",
            "name": "Hydrocarbon Ingress & Blending System",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-100",
            "subsystems": [
                "Feed Supply Header (TP-01)",
                "Feed Pressure Sensing Branch",
                "Feed Surge & Degassing Unit (V-101)",
                "Feed Motive Pumping Station (P-101A/B)"
            ]
        },
        {
            "system_id": "SYS-200",
            "name": "Catalytic Reaction & Hydrogen Addition System",
            "plant": "Refinery Plant 2",
            "unit": "Unit 100 - Hydrotreater",
            "area": "AREA-200",
            "subsystems": [
                "Packed Bed Reactor Station (R-201)",
                "Heat Recovery & Preheating Station (E-201)",
                "Reactor Temperature & Pressure Control Loop",
                "Overpressure Flare Header (PSV-2041)",
                "Effluent Return Header (TP-02)"
            ]
        }
    ]
    systems_col.insert_many(systems_data)
    print(f"Successfully seeded {len(systems_data)} systems into {DB_NAME}.systems!")
    
    # 3. Create Indexes
    assets_col.create_index([("tag_number", pymongo.ASCENDING)], unique=True)
    assets_col.create_index([("location.plant", pymongo.ASCENDING), ("location.unit", pymongo.ASCENDING), ("location.area", pymongo.ASCENDING)])
    print("Created indexes on tag_number and location hierarchy.")
    
    print(f"\nAll databases in cluster: {client.list_database_names()}")
    print(f"Collections in {DB_NAME}: {db.list_collection_names()}")
    print(f"Total asset count in {DB_NAME}.assets: {assets_col.count_documents({})}")


if __name__ == "__main__":
    seed_enstudio_database()
