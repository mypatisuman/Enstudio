"""
Tests for adapters/mongodb.py — verifying MongoDB / CosmosDB connection
and queries using configurations from mongo.env.
"""
import os
import sys
from pathlib import Path
import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from adapters import mongodb as M

# These four tests talk to a REAL MongoDB/CosmosDB cluster over the network.
# They are therefore conditional: the adapter no longer carries a hardcoded
# fallback connection string (that credential was removed and must be treated
# as compromised), so a checkout without MONGODB_URI configured has nothing to
# connect to and must skip rather than fail.
_HAS_MONGO = bool((os.getenv("MONGODB_URI") or "").strip())

pytestmark = pytest.mark.skipif(
    not _HAS_MONGO,
    reason="MONGODB_URI is not configured - copy mongo.env.example to "
           "mongo.env and set it to run the live MongoDB integration tests.",
)


def test_mongodb_connection_health():
    """Verifies that MongoDB connects successfully to the Enstudio database."""
    health = M.check_mongo_connection()
    assert health["status"] == "connected", f"MongoDB connection failed: {health.get('error')}"
    assert "Enstudio" in health["databases"]
    assert health["current_database"] == "Enstudio"
    assert "assets" in health["collections"]
    assert "systems" in health["collections"]


def test_mongodb_fetch_asset_inventory():
    """Verifies fetching physical asset inventory from Enstudio.assets."""
    assets = M.fetch_asset_inventory(limit=10)
    assert isinstance(assets, list)
    assert len(assets) > 0
    first = assets[0]
    assert "tag_number" in first
    assert "location" in first
    assert "specifications" in first


def test_mongodb_fetch_plant_hierarchy():
    """Verifies extracting plant, unit, area, and system hierarchy from Enstudio."""
    hierarchy = M.fetch_plant_hierarchy()
    assert isinstance(hierarchy, dict)
    assert "plants" in hierarchy
    assert "units" in hierarchy
    assert "areas" in hierarchy
    assert "systems" in hierarchy
    assert "Refinery Plant 2" in hierarchy["plants"]
    assert "Unit 100 - Hydrotreater" in hierarchy["units"]


def test_mongodb_fetch_asset_by_tag():
    """Verifies looking up an asset by exact tag from Enstudio."""
    pt = M.fetch_asset_by_tag("PT-101")
    assert pt is not None
    assert pt["tag_number"] == "PT-101"
    assert pt["specifications"]["manufacturer"] == "Emerson Rosemount"
    assert pt["specifications"]["model"] == "3051S Coplanar Pressure Transmitter"

    # Also test looking up Tie-In point
    tp = M.fetch_asset_by_tag("TP-01")
    assert tp is not None
    assert tp["tag_number"] == "TP-01"
    assert tp["specifications"]["line_size"] == "4 inch"

