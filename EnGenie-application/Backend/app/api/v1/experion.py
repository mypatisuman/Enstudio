"""
FastAPI Routes for Honeywell Experion PKS (C300 CEE) Integration.
Endpoints for P&ID loop inference, Control Builder XML & Point Builder CSV generation,
and live OPC UA runtime interfacing.
"""

import logging
from typing import Any
from fastapi import APIRouter, Request, Response
from app.core.security import login_required
from common.helpers.responses import JSONResponse
from domain.experion.schemas import (
    ExperionStrategy,
    OPCConnectionConfig,
    OPCWriteRequest,
)
from domain.experion.services.experion_builder_exporter import (
    generate_control_builder_xml,
    generate_point_builder_csv,
)
from domain.experion.services.experion_inference_service import infer_experion_strategy
from domain.experion.services.experion_opc_service import experion_opc_manager

logger = logging.getLogger(__name__)

blueprint = APIRouter(prefix="/api/experion", tags=["Experion DCS"])


@blueprint.post("/infer")
@login_required
async def api_infer_experion_strategy(request: Request):
    """
    Infers Honeywell Experion C300 Control Modules, CEE function blocks,
    and wire interconnects from a P&ID graph payload.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    pid_graph_data = body.get("pid_graph") or body.get("pidGraph") or body
    controller_name = body.get("controller_name", "CEE01_C300")

    try:
        strategy: ExperionStrategy = infer_experion_strategy(
            pid_graph_data=pid_graph_data,
            controller_name=controller_name,
        )
        # Pre-seed OPC manager with inferred tags
        experion_opc_manager.register_strategy(strategy.model_dump())

        return JSONResponse({
            "success": True,
            "strategy": strategy.model_dump(),
        }, status_code=200)
    except Exception as e:
        logger.exception("Failed to infer Experion strategy from P&ID")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/export-xml")
@login_required
async def api_export_control_builder_xml(request: Request):
    """
    Generates downloadable Honeywell Control Builder XML file for C300 controllers.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    strategy_data = body.get("strategy")
    if not strategy_data:
        # Infer on the fly if pid_graph was passed directly
        pid_graph = body.get("pid_graph") or body.get("pidGraph") or body
        controller_name = body.get("controller_name", "CEE01_C300")
        strategy_obj = infer_experion_strategy(pid_graph, controller_name)
    else:
        strategy_obj = ExperionStrategy.model_validate(strategy_data)

    try:
        xml_content = generate_control_builder_xml(strategy_obj)
        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="experion_c300_{strategy_obj.target_controller}_strategy.xml"',
            },
        )
    except Exception as e:
        logger.exception("Failed to generate Control Builder XML")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/export-csv")
@login_required
async def api_export_point_builder_csv(request: Request):
    """
    Generates downloadable Honeywell Point Builder CSV tag database file.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    strategy_data = body.get("strategy")
    if not strategy_data:
        pid_graph = body.get("pid_graph") or body.get("pidGraph") or body
        controller_name = body.get("controller_name", "CEE01_C300")
        strategy_obj = infer_experion_strategy(pid_graph, controller_name)
    else:
        strategy_obj = ExperionStrategy.model_validate(strategy_data)

    try:
        csv_content = generate_point_builder_csv(strategy_obj)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="experion_c300_point_builder_tags.csv"',
            },
        )
    except Exception as e:
        logger.exception("Failed to generate Point Builder CSV")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/opc/connect")
@login_required
async def api_opc_connect(request: Request):
    """Connects or initializes OPC UA bridge to Honeywell Experion OPC Server."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = OPCConnectionConfig.model_validate(body)
    result = experion_opc_manager.connect(config)
    return JSONResponse(result, status_code=200)


@blueprint.post("/opc/disconnect")
@login_required
async def api_opc_disconnect():
    """Disconnects OPC UA session."""
    result = experion_opc_manager.disconnect()
    return JSONResponse(result, status_code=200)


@blueprint.get("/opc/tags")
@login_required
async def api_opc_read_tags():
    """Reads live runtime PV, SP, OP, and Mode values for all active Experion loops."""
    tags = experion_opc_manager.read_all_tags()
    return JSONResponse({
        "success": True,
        "is_connected": experion_opc_manager.is_connected,
        "simulation_mode": experion_opc_manager.simulation_mode,
        "endpoint_url": experion_opc_manager.endpoint_url,
        "tags": [t.model_dump() for t in tags],
    }, status_code=200)


@blueprint.post("/opc/write")
@login_required
async def api_opc_write_tag(request: Request):
    """Writes a Setpoint, Output, or Controller Mode to an Experion CEE block."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        write_req = OPCWriteRequest.model_validate(body)
        result = experion_opc_manager.write_tag(write_req)
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logger.exception("Failed to write to Experion tag")
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
