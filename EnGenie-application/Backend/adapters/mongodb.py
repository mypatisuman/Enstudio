"""
adapters/mongodb.py — MongoDB connection manager and repository queries for EnSTUDIO.

Reads connection strings and credentials from environment variables / mongo.env:
- MONGODB_URI
- MONGODB_DATABASE (default: "product-recommender")
- RESTRUCTURED_DB_URI
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
import pymongo
from dotenv import load_dotenv

# Load environment variables: studio/.env first, then mongo.env
_STUDIO_DIR = Path(__file__).resolve().parent.parent
_STUDIO_ENV_PATH = _STUDIO_DIR / ".env"
_REPO_ROOT = _STUDIO_DIR.parent
_MONGO_ENV_PATH = _REPO_ROOT / "mongo.env"

if _STUDIO_ENV_PATH.exists():
    load_dotenv(_STUDIO_ENV_PATH, override=True)
elif _MONGO_ENV_PATH.exists():
    load_dotenv(_MONGO_ENV_PATH, override=True)
else:
    load_dotenv()

# NO HARDCODED CREDENTIAL DEFAULT.
#
# This module used to carry a live connection string — username, password and
# cluster host — as the fallback value for MONGODB_URI. That meant the
# credential shipped inside the source tree, and any checkout could connect to
# the production cluster without configuring anything. The URI is now read
# from the environment only; an unset value raises MissingMongoCredentials at
# CALL time (never at import time, so tests and tooling can still import this
# module on a machine with no Mongo configured).
DEFAULT_MONGO_DB = os.getenv("MONGODB_DATABASE", "Enstudio")


class MissingMongoCredentials(RuntimeError):
    """Raised when a Mongo call is made with no connection string configured."""


def _require_uri(uri: Optional[str], env_var: str) -> str:
    """Resolve a connection string from the argument or the environment.

    Raises MissingMongoCredentials with an actionable message rather than
    silently falling back to a baked-in cluster.
    """
    resolved = (uri or os.getenv(env_var) or "").strip()
    if not resolved:
        raise MissingMongoCredentials(
            f"{env_var} is not set. Copy mongo.env.example to mongo.env and "
            f"set {env_var} to your own connection string. There is "
            f"deliberately no built-in default — the previous hardcoded "
            f"credential has been removed and must be treated as compromised."
        )
    return resolved


def get_mongo_uri() -> str:
    """Primary cluster URI. Raises MissingMongoCredentials when unset."""
    return _require_uri(None, "MONGODB_URI")


def get_restructured_uri() -> str:
    """Cluster B URI, falling back to the primary cluster when unset."""
    explicit = (os.getenv("RESTRUCTURED_DB_URI") or "").strip()
    return explicit or get_mongo_uri()


_client_cache: dict[str, pymongo.MongoClient] = {}


def get_mongo_client(uri: Optional[str] = None) -> pymongo.MongoClient:
    """Returns a cached pymongo MongoClient for the given URI."""
    target_uri = _require_uri(uri, "MONGODB_URI")
    if target_uri not in _client_cache:
        _client_cache[target_uri] = pymongo.MongoClient(
            target_uri,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=30000,
        )
    return _client_cache[target_uri]


def get_mongo_db(db_name: Optional[str] = None, uri: Optional[str] = None) -> pymongo.database.Database:
    """Returns the pymongo Database object for the target database."""
    client = get_mongo_client(uri)
    target_db = db_name or os.getenv("MONGODB_DATABASE", DEFAULT_MONGO_DB)
    return client[target_db]


def get_restructured_db() -> pymongo.database.Database:
    """Returns the Database for Restructured hierarchy (Cluster B)."""
    return get_mongo_db(db_name="Restructured", uri=get_restructured_uri())


def check_mongo_connection() -> dict[str, Any]:
    """Healthcheck to verify MongoDB connection and list available collections."""
    try:
        client = get_mongo_client()
        dbs = client.list_database_names()
        db = get_mongo_db()
        collections = db.list_collection_names()
        return {
            "status": "connected",
            "databases": dbs,
            "current_database": db.name,
            "collections_count": len(collections),
            "collections": collections,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "database": DEFAULT_MONGO_DB,
        }


def fetch_asset_inventory(
    plant: Optional[str] = None,
    unit: Optional[str] = None,
    area: Optional[str] = None,
    system: Optional[str] = None,
    tag_number: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch physical asset inventory from Enstudio.assets matching location/system/tag filters."""
    try:
        db = get_mongo_db()
        query: dict[str, Any] = {}
        if plant:
            query["location.plant"] = {"$regex": plant, "$options": "i"}
        if unit:
            query["location.unit"] = {"$regex": unit, "$options": "i"}
        if area:
            query["location.area"] = {"$regex": area, "$options": "i"}
        if system:
            query["location.system"] = {"$regex": system, "$options": "i"}
        if tag_number:
            query["$or"] = [
                {"tag_number": {"$regex": f"^{tag_number.strip()}$", "$options": "i"}},
                {"specifications.tag_number": {"$regex": f"^{tag_number.strip()}$", "$options": "i"}},
                {"asset.tag_number": {"$regex": f"^{tag_number.strip()}$", "$options": "i"}},
            ]

        # First check in assets collection
        docs = list(db.assets.find(query, {"_id": 0}).limit(limit))
        if not docs and "asset_configurations" in db.list_collection_names():
            docs = list(db.asset_configurations.find(query, {"_id": 0}).limit(limit))
        return docs
    except Exception as e:
        print(f"[mongodb] Error fetching asset inventory: {e}")
        return []


def fetch_plant_hierarchy() -> dict[str, Any]:
    """Extract distinct plant, unit, area, and system hierarchies from MongoDB."""
    try:
        db = get_mongo_db()
        plants = set(db.assets.distinct("location.plant"))
        units = set(db.assets.distinct("location.unit"))
        areas = set(db.assets.distinct("location.area"))
        systems = set(db.assets.distinct("location.system"))
        
        # Also check systems collection
        if "systems" in db.list_collection_names():
            for sys_doc in db.systems.find({}, {"_id": 0}):
                if sys_doc.get("plant"):
                    plants.add(sys_doc["plant"])
                if sys_doc.get("unit"):
                    units.add(sys_doc["unit"])
                if sys_doc.get("area"):
                    areas.add(sys_doc["area"])
                if sys_doc.get("name"):
                    systems.add(sys_doc["name"])

        return {
            "plants": sorted([p for p in plants if p]),
            "units": sorted([u for u in units if u]),
            "areas": sorted([a for a in areas if a]),
            "systems": sorted([s for s in systems if s]),
        }
    except Exception as e:
        print(f"[mongodb] Error fetching plant hierarchy: {e}")
        return {"plants": [], "units": [], "areas": [], "systems": []}


def fetch_asset_by_tag(tag_number: str) -> Optional[dict[str, Any]]:
    """Look up full physical specifications for an exact instrument/equipment tag."""
    if not tag_number:
        return None
    tag_clean = tag_number.strip()
    try:
        db = get_mongo_db()
        # Search in Enstudio.assets
        doc = db.assets.find_one(
            {
                "$or": [
                    {"tag_number": {"$regex": f"^{tag_clean}$", "$options": "i"}},
                    {"specifications.tag_number": {"$regex": f"^{tag_clean}$", "$options": "i"}},
                ]
            },
            {"_id": 0}
        )
        if doc:
            return doc

        # Fallback to asset_configurations if available
        if "asset_configurations" in db.list_collection_names():
            doc2 = db.asset_configurations.find_one(
                {"asset.tag_number": {"$regex": f"^{tag_clean}$", "$options": "i"}},
                {"_id": 0}
            )
            if doc2:
                return doc2

        return None
    except Exception as e:
        print(f"[mongodb] Error finding asset tag {tag_number}: {e}")
        return None

