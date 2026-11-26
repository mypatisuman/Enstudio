from common.helpers.azure_session import get_session
"""Asset Configs domain routes."""
import logging
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.core.errors import notify_failure

from common.helpers.responses import JSONResponse

blueprint = APIRouter()


@blueprint.get("/api/asset-configurations")
@login_required
async def api_list_asset_configurations(request: Request):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        from common.ai.rag.assets_rag import list_configurations
        configs = list_configurations(user_id)
        return JSONResponse({"success": True, "configurations": configs}, status_code=200)
    except Exception as e:
        logging.exception("Failed to list asset configurations")
        notify_failure("Asset Configurations List", str(e), page="asset_configs", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/api/asset-configurations")
@login_required
async def api_create_asset_configuration(request: Request):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        try:
            data = await request.json()
        except Exception:
            data = {}
        from common.helpers.config_validator import validate_required_equipment_fields
        valid, missing = validate_required_equipment_fields(data)
        if not valid:
            return JSONResponse({
                "success": False,
                "error":   "missing_required_fields",
                "missing": missing,
                "message": "Please provide the following before saving: " + ", ".join(missing),
            }, status_code=422)
        from common.ai.rag.assets_rag import create_configuration
        result = create_configuration(user_id, data)
        status = 201 if result.get("success") else 500
        return JSONResponse(result, status_code=status)
    except Exception as e:
        logging.exception("Failed to create asset configuration")
        notify_failure("Asset Configuration Create", str(e), page="asset_configs", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/api/asset-configurations/extract-from-text")
@login_required
async def api_asset_config_extract_from_text(request: Request):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        try:
            data = await request.json()
        except Exception:
            data = {}
        message = data.get("message", "").strip()
        if not message:
            return JSONResponse({"success": False, "error": "message is required"}, status_code=400)
        context = data.get("context")
        from common.ai.rag.assets_rag import extract_config_from_text
        result = extract_config_from_text(message, user_id, context=context)
        status = 200 if result.get("success") else 500
        return JSONResponse(result, status_code=status)
    except Exception as e:
        logging.exception("Failed to extract asset config from text")
        notify_failure("Asset Config Extract from Text", str(e), page="asset_configs", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.get("/api/asset-configurations/standards")
@login_required
async def api_get_asset_standards(request: Request):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        asset_type = request.query_params.get("asset_type", "").strip()
        if not asset_type:
            return JSONResponse({"success": False, "error": "asset_type is required"}, status_code=400)

        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
        result = ProductHierarchyRepository.get_standards_for_category(user_id, asset_type)
        return JSONResponse({"success": True, **result}, status_code=200)
    except Exception as e:
        logging.exception("Failed to fetch asset standards")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.put("/api/asset-configurations/{configuration_id}")
@login_required
async def api_update_asset_configuration(request: Request, configuration_id: str):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        try:
            data = await request.json()
        except Exception:
            data = {}
        from common.ai.rag.assets_rag import (
            build_user_id_filter,
            get_asset_config_collection,
            update_configuration,
        )
        from common.helpers.config_validator import validate_required_equipment_fields
        collection = get_asset_config_collection()
        existing: dict = {}
        if collection is not None:
            existing = collection.find_one(
                build_user_id_filter(user_id, {"configuration_id": configuration_id})
            ) or {}
        merged: dict = {}
        for section in ("asset", "location", "connected_system", "target_system",
                        "relationships", "instrument_config"):
            merged[section] = {**(existing.get(section) or {}), **(data.get(section) or {})}
        valid, missing = validate_required_equipment_fields(merged)
        if not valid:
            return JSONResponse({
                "success": False,
                "error":   "missing_required_fields",
                "missing": missing,
                "message": "Please provide the following before saving: " + ", ".join(missing),
            }, status_code=422)
        result = update_configuration(user_id, configuration_id, data)
        status = 200 if result.get("success") else (404 if "not found" in result.get("error", "").lower() else 500)
        return JSONResponse(result, status_code=status)
    except Exception as e:
        logging.exception("Failed to update asset configuration")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/api/asset-configurations/{configuration_id}/generate-yaml")
@login_required
async def api_generate_yaml_for_config(request: Request, configuration_id: str):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        from common.ai.rag.assets_rag import generate_yaml_for_config
        result = generate_yaml_for_config(configuration_id, user_id)
        if result.get("error") == "missing_required_fields":
            return JSONResponse(result, status_code=422)
        status = 200 if result.get("success") else (404 if "not found" in result.get("error", "").lower() else 500)
        return JSONResponse(result, status_code=status)
    except Exception as e:
        logging.exception("Failed to generate YAML for asset configuration")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.delete("/api/asset-configurations/{configuration_id}")
@login_required
async def api_delete_asset_configuration(request: Request, configuration_id: str):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        from common.ai.rag.assets_rag import delete_configuration
        result = delete_configuration(user_id, configuration_id)
        status = 200 if result.get("success") else (404 if "not found" in result.get("error", "").lower() else 500)
        return JSONResponse(result, status_code=status)
    except Exception as e:
        logging.exception("Failed to delete asset configuration")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
