"""
Standardization Helpers

Pure utility functions for standardizing product data structures.
These are helper functions called by standardization tools, not standalone tools.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# MODEL/SUBMODEL STANDARDIZATION HELPERS
# ============================================================================

def standardize_matched_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Standardize a list of matched models using LLM."""
    standardized = []
    for model in models:
        try:
            from common.tools.llm_analysis.standardization_tool import standardize_data
            raw_data = {
                "vendor": model.get("vendor", ""),
                "product_type": model.get("product_type", ""),
                "model_family": model.get("model_series", ""),
                "specifications": model.get("specifications", {})
            }
            standardized_data = standardize_data(raw_data, "Matched model standardization")
            standardized_model = model.copy()
            standardized_model.update({
                "vendor": standardized_data.get("vendor", model.get("vendor", "")),
                "product_type": standardized_data.get("product_type", model.get("product_type", "")),
                "model_series": standardized_data.get("model_family", model.get("model_series", ""))
            })
            standardized.append(standardized_model)
        except Exception as e:
            logger.error(f"[HELPERS] Failed to standardize model: {e}")
            standardized.append(model)
    return standardized


def standardize_models_list(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Standardize a list of models (wrapper for standardize_matched_models)."""
    return standardize_matched_models(models)


def standardize_submodels_list(submodels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Standardize a list of submodels."""
    standardized = []
    for submodel in submodels:
        try:
            if "specifications" in submodel:
                standardized_specs = standardize_specifications(submodel["specifications"])
                submodel_copy = submodel.copy()
                submodel_copy["specifications"] = standardized_specs
                standardized.append(submodel_copy)
            else:
                standardized.append(submodel)
        except Exception as e:
            logger.error(f"[HELPERS] Failed to standardize submodel: {e}")
            standardized.append(submodel)
    return standardized


def standardize_specifications(specs: dict[str, Any]) -> dict[str, Any]:
    """Standardize specification keys and values using LLM."""
    if not specs:
        return specs
    try:
        from common.tools.llm_analysis.standardization_tool import standardize_data
        raw_data = {"vendor": "", "product_type": "", "model_family": "", "specifications": specs}
        result = standardize_data(raw_data, "Specification standardization")
        return result.get("specifications", specs)
    except Exception as e:
        logger.error(f"[HELPERS] Failed to standardize specifications: {e}")
        return specs


def enhance_submodel_mapping(submodel_data: dict[str, Any]) -> dict[str, Any]:
    """Enhanced submodel to model series mapping using standardization."""
    if not submodel_data:
        return submodel_data
    try:
        from common.tools.llm_analysis.standardization_tool import standardize_data
        raw_data = {
            "vendor": submodel_data.get("vendor", ""),
            "product_type": submodel_data.get("product_type", ""),
            "model_family": submodel_data.get("model_series", ""),
            "specifications": {}
        }
        if "sub_models" in submodel_data:
            for sub_model in submodel_data["sub_models"]:
                if "specifications" in sub_model:
                    raw_data["specifications"].update(sub_model["specifications"])
        context = f"Submodel mapping for {submodel_data.get('model_series', 'Unknown')} series"
        standardized = standardize_data(raw_data, context)
        result = submodel_data.copy()
        result.update({
            "vendor": standardized.get("vendor", submodel_data.get("vendor", "")),
            "product_type": standardized.get("product_type", submodel_data.get("product_type", "")),
            "model_series": standardized.get("model_family", submodel_data.get("model_series", "")),
            "standardization_confidence": standardized.get("confidence", 1.0)
        })
        if "sub_models" in result:
            result["sub_models"] = standardize_submodels_list(result["sub_models"])
        return result
    except Exception as e:
        logger.error(f"[HELPERS] Failed to enhance submodel mapping: {e}")
        return submodel_data


def standardize_product_image_mapping(image_data: dict[str, Any]) -> dict[str, Any]:
    """Standardize product image mapping data."""
    if not image_data:
        return image_data
    try:
        from common.tools.llm_analysis.standardization_tool import standardize_data
        raw_data = {
            "vendor": image_data.get("vendor", ""),
            "product_type": image_data.get("product_type", ""),
            "model_family": image_data.get("model_name", ""),
            "specifications": {}
        }
        context = f"Product image mapping for {image_data.get('model_name', 'Unknown')}"
        standardized = standardize_data(raw_data, context)
        result = image_data.copy()
        result.update({
            "vendor": standardized.get("vendor", image_data.get("vendor", "")),
            "product_type": standardized.get("product_type", image_data.get("product_type", "")),
            "model_name": standardized.get("model_family", image_data.get("model_name", "")),
            "standardization_confidence": standardized.get("confidence", 1.0)
        })
        return result
    except Exception as e:
        logger.error(f"[HELPERS] Failed to standardize product image mapping: {e}")
        return image_data


def suggest_analysis_product_type(product_type: str) -> str:
    """DEPRECATED: Use get_search_categories() instead. Kept for backward compatibility."""
    logger.warning("[HELPERS] suggest_analysis_product_type() is DEPRECATED.")
    try:
        from domain.search.agents.deep_analysis_agent import _split_product_type
        search_categories = _split_product_type(product_type)
        return search_categories[0] if search_categories else product_type
    except Exception as e:
        logger.error(f"[HELPERS] Failed to get search categories: {e}")
        return product_type
