"""
Response formatting utilities for the Engenie backend.

Provides:
- convert_keys_to_camel_case  — recursively converts snake_case keys → camelCase
- Vendor/product standardisation helpers (delegated to common.helpers.standardization_helpers)
"""
import logging
import re
from common.helpers.responses import JSONResponse


# ══════════════════════════════════════════════════════════════════════════
# CAMEL CASE CONVERSION
# ══════════════════════════════════════════════════════════════════════════

def convert_keys_to_camel_case(obj):
    """Recursively convert all dict keys from snake_case to camelCase."""
    if isinstance(obj, dict):
        return {
            re.sub(r'_([a-z])', lambda m: m.group(1).upper(), k): convert_keys_to_camel_case(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [convert_keys_to_camel_case(item) for item in obj]
    return obj


# ══════════════════════════════════════════════════════════════════════════
# VENDOR / PRODUCT STANDARDISATION WRAPPERS
# ══════════════════════════════════════════════════════════════════════════

def standardize_vendor_name(name: str) -> str:
    """Lightweight vendor name normalisation (title-case, trim)."""
    if not name:
        return name
    return name.strip().title()


def standardize_vendor_analysis_result(data: dict) -> dict:
    """Pass-through standardisation for vendor analysis dicts.
    Extend this function with LLM-based cleanup logic if needed."""
    if not isinstance(data, dict):
        return data
    return data


def standardize_ranking_result(data: dict) -> dict:
    """Pass-through standardisation for ranking result dicts."""
    if not isinstance(data, dict):
        return data
    return data


def standardize_product_match(data: dict) -> dict:
    """Pass-through standardisation for a single product match dict."""
    if not isinstance(data, dict):
        return data
    return data


def standardize_and_convert_response(data):
    """Apply standardisation then convert keys to camelCase."""
    if not isinstance(data, dict):
        return convert_keys_to_camel_case(data)
    standardized = _apply_standardization(data)
    return convert_keys_to_camel_case(standardized)


# ── Internal helper ────────────────────────────────────────────────────────

def _apply_standardization(data: dict) -> dict:
    """Apply appropriate standardisation based on key names in data."""
    standardized = data.copy()
    for key, value in data.items():
        if key in ("vendor_analysis", "vendorAnalysis") and isinstance(value, dict):
            try:
                standardized[key] = standardize_vendor_analysis_result(value)
            except Exception as e:
                logging.warning(f"Failed to standardize vendor analysis: {e}")
        elif key in ("overall_ranking", "overallRanking", "ranking") and isinstance(value, dict):
            try:
                standardized[key] = standardize_ranking_result(value)
            except Exception as e:
                logging.warning(f"Failed to standardize ranking: {e}")
        elif key == "vendors" and isinstance(value, list):
            standardized_vendors = []
            for vendor in value:
                if isinstance(vendor, dict) and "name" in vendor:
                    vendor_copy = vendor.copy()
                    try:
                        vendor_copy["name"] = standardize_vendor_name(vendor.get("name", ""))
                    except Exception as e:
                        logging.warning(f"Failed to standardize vendor name: {e}")
                    standardized_vendors.append(vendor_copy)
                else:
                    standardized_vendors.append(vendor)
            standardized[key] = standardized_vendors
    return standardized

