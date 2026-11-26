"""
Solution domain routes.

Endpoints:
  POST /api/solution-agent              — async solution orchestrator (returns 202 Accepted + stream_id)
                                          Processes in background thread, emits progress events
  GET  /api/solution-status/{stream_id} — polling endpoint for progress/results
                                          Returns accumulated events and final result when complete
  GET  /api/generic_image/{product_type} — generic product type image with MongoDB caching
  GET  /api/image_proxy                 — proxies Azure Blob images through the backend (local dev)
"""
import json
import logging
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Response
from common.helpers.responses import JSONResponse

from app.core.errors import notify_failure
from app.core.security import login_required
from common.helpers.azure_session import get_session
from common.infra.repositories.interaction_log_repository import interaction_logger
from common.services import credit_service

blueprint = APIRouter()


@blueprint.post("/api/solution-agent")
@login_required
async def solution_agent(request: Request):
    session = get_session(request)

    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        user_input = data.get("user_input", "").strip()

        if not user_input:
            return JSONResponse({"error": "user_input is required"}, status_code=400)

        stream_id = data.get("stream_id") or str(uuid.uuid4())
        user_id = session.get('user_id')

        credit_gate = credit_service.check_workflow_allowed(user_id, "solution")
        if not credit_gate.get("allowed", True):
            return JSONResponse({
                "error": "Insufficient credits",
                "message": credit_gate.get("reason") or "You do not have enough credits to run the solution agent.",
                "required_credits": credit_gate.get("cost"),
                "balance": credit_gate.get("balance"),
            }, status_code=402)

        from common.helpers.progress_tracker import progress_tracker
        progress_tracker.create_stream(stream_id)

        kwargs = {
            "user_input": user_input,
            "current_instruments": data.get("current_instruments"),
            "current_accessories": data.get("current_accessories"),
            "awaiting_single_item_confirmation": data.get("awaiting_single_item_confirmation", False),
            "awaiting_holistic_confirmation": data.get("awaiting_holistic_confirmation") or data.get("awaiting_comprehensiveness_confirmation", False),
            "search_session_id": data.get("search_session_id") or data.get("user_session_id"),
            "user_session_id": data.get("user_session_id"),
            "user_id": user_id,
            "context_memory": data.get("context_memory", []),
            "stream_id": stream_id,
            "enable_streaming": True, # Still emit progress to stream
            "skip_standards": data.get("skip_standards", False),
        }

        # ── BACKGROUND EXECUTION RUNTIME ──────────────────────────────────
        # Execute the heavy LangGraph pipeline in a background thread and return
        # a 202 Accepted immediately so the frontend can poll for the result.
        from common.services.agentic_integration import run_project_intent
        import threading
        
        credit_service.register_workflow_run(
            stream_id, user_id, "solution", session_id=kwargs.get("search_session_id"),
        )

        def _background_solution_worker():
            try:
                from common.monitoring.benchmarking import live
                with live.capture("solution", user_input=kwargs.get("user_input", ""), user_id=kwargs.get("user_id")):
                    final_result = run_project_intent(**kwargs)
                status_code = 200
                if final_result.get("success", True) is False and final_result.get("intent") == "error":
                    status_code = 500
                    progress_tracker.emit(stream_id, "error", final_result)
                else:
                    from common.helpers.notifications import notify_task_completion
                    notify_task_completion(
                        title="Solution Analysis Ready",
                        message="Your engineering solution BOM and instrument recommendations are ready.",
                        user_id=user_id,
                        page="solution",
                        task_type="solution_generation",
                        stream_id=stream_id,
                    )
                    progress_tracker.emit(stream_id, "task_complete", {
                        "title": "Solution Analysis Ready",
                        "message": "Engineering BOM and instrument recommendations are ready.",
                        "sound": True,
                        "task_type": "solution",
                        "stream_id": stream_id,
                    })
                    progress_tracker.emit(stream_id, "result", final_result)
                # run_project_intent failures return success=False without intent="error",
                # so charge strictly on the success flag — failed runs are never charged
                credit_service.settle_workflow_run(
                    stream_id, success=final_result.get("success", True) is not False,
                )
            except Exception as e:
                logging.error(f"[SOLUTION] Background execution crashed: {e}")
                progress_tracker.emit(stream_id, "error", {"message": str(e), "intent": "error"})
                credit_service.settle_workflow_run(stream_id, success=False)
            finally:
                progress_tracker.close_stream(stream_id, reason="solution-worker-finished")

        threading.Thread(target=_background_solution_worker, daemon=True, name=f"solution-worker-{stream_id}").start()
        
        return JSONResponse({
            "success": True,
            "status": "processing",
            "stream_id": stream_id,
            "message": "Processing started in the background."
        }, status_code=202)

    except Exception as e:
        logging.exception("[SOLUTION_AGENT] Request handling failed")
        notify_failure("Solution Agent Processing", str(e), page="solution", user_id=session.get('user_id'))
        return JSONResponse({
            "error": f"Failed to start processing: {e}",
            "intent": "error"
        }, status_code=500)

@blueprint.get("/api/solution-status/{stream_id}")
@login_required
async def solution_status(request: Request, stream_id: str):
    session = get_session(request)
    
    if not stream_id:
        return JSONResponse({"error": "Stream ID required"}, status_code=400)

    from common.helpers.progress_tracker import progress_tracker
    events = progress_tracker.consume_events(stream_id)
    
    final_result = progress_tracker.get_final_result(stream_id)
    if final_result and not any(e.get("type") in ("result", "error") for e in events):
        events.append(final_result)

    if not events:
        return JSONResponse({"status": "waiting", "events": []}, status_code=200)

    return JSONResponse({"status": "events", "events": events}, status_code=200)


@blueprint.get("/api/solution-data/{stream_id}")
@login_required
async def get_solution_data(request: Request, stream_id: str):
    """Retrieve raw workflow execution data and results by stream_id."""
    session = get_session(request)
    if not stream_id:
        return JSONResponse({"error": "Stream ID required"}, status_code=400)

    from common.helpers.progress_tracker import progress_tracker
    final_result = progress_tracker.get_final_result(stream_id)
    if not final_result:
        return JSONResponse({"error": "No workflow data found for the provided stream ID", "stream_id": stream_id}, status_code=404)

    return JSONResponse({
        "workflow": "solution_workflow",
        "stream_id": stream_id,
        "data": final_result
    }, status_code=200)


@blueprint.post("/api/solution/export-data")
@login_required
async def export_solution_data(request: Request):
    """Server-side endpoint to format and download solution workflow input & output data."""
    session = get_session(request)
    try:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        export_format = (payload.get("format") or payload.get("export_format") or "json").lower()
        project_name = (payload.get("project_name") or "solution").strip()
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in project_name.lower())[:35] or "solution"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if export_format == "csv":
            import csv
            import io

            instruments = payload.get("instruments") or (payload.get("output_data") or {}).get("instruments") or []
            accessories = payload.get("accessories") or (payload.get("output_data") or {}).get("accessories") or []

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Item Type",
                "Category",
                "Product / Accessory Name",
                "Quantity",
                "Key Specifications",
                "Applicable Standards",
                "Specified Vendors",
                "Specified Model Families",
                "Procurement Strategy",
                "Parent Instrument Category",
                "Standards Summary"
            ])

            for inst in instruments:
                specs = inst.get("specifications") or {}
                spec_str = "; ".join(f"{k}: {v}" for k, v in specs.items()) if isinstance(specs, dict) else str(specs)
                stds = "; ".join(inst.get("applicableStandards") or inst.get("applicable_standards") or []) if isinstance(inst.get("applicableStandards") or inst.get("applicable_standards"), list) else str(inst.get("applicableStandards") or "")
                vendors = "; ".join(inst.get("specifiedVendors") or inst.get("specified_vendors") or []) if isinstance(inst.get("specifiedVendors") or inst.get("specified_vendors"), list) else str(inst.get("specifiedVendors") or "")
                models = "; ".join(inst.get("specifiedModelFamilies") or inst.get("specified_model_families") or []) if isinstance(inst.get("specifiedModelFamilies") or inst.get("specified_model_families"), list) else str(inst.get("specifiedModelFamilies") or "")

                writer.writerow([
                    "Instrument",
                    inst.get("category", ""),
                    inst.get("productName") or inst.get("product_name") or inst.get("name", ""),
                    inst.get("quantity", 1),
                    spec_str,
                    stds,
                    vendors,
                    models,
                    inst.get("strategy", ""),
                    "",
                    inst.get("standardsSummary") or inst.get("standards_summary", "")
                ])

            for acc in accessories:
                specs = acc.get("specifications") or {}
                spec_str = "; ".join(f"{k}: {v}" for k, v in specs.items()) if isinstance(specs, dict) else str(specs)
                stds = "; ".join(acc.get("applicableStandards") or acc.get("applicable_standards") or []) if isinstance(acc.get("applicableStandards") or acc.get("applicable_standards"), list) else str(acc.get("applicableStandards") or "")
                vendors = "; ".join(acc.get("specifiedVendors") or acc.get("specified_vendors") or []) if isinstance(acc.get("specifiedVendors") or acc.get("specified_vendors"), list) else str(acc.get("specifiedVendors") or "")

                writer.writerow([
                    "Accessory",
                    acc.get("category", ""),
                    acc.get("accessoryName") or acc.get("accessory_name") or acc.get("name", ""),
                    acc.get("quantity", 1),
                    spec_str,
                    stds,
                    vendors,
                    "",
                    acc.get("strategy", ""),
                    acc.get("parentInstrumentCategory") or acc.get("parent_instrument_category", ""),
                    acc.get("standardsSummary") or acc.get("standards_summary", "")
                ])

            csv_data = output.getvalue()
            return Response(
                content=csv_data,
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename={safe_name}_bom_{timestamp}.csv"
                }
            )

        # JSON format
        export_package = {
            "workflow": "solution_workflow",
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "project_name": project_name,
            "input_data": payload.get("input_data") or {
                "user_requirements": payload.get("user_requirements") or payload.get("user_input") or "",
                "standards_enabled": payload.get("standards_enabled", True)
            },
            "output_data": payload.get("output_data") or {
                "instruments": payload.get("instruments", []),
                "accessories": payload.get("accessories", []),
                "designed_solution": payload.get("designed_solution"),
            }
        }

        json_bytes = json.dumps(export_package, indent=2).encode("utf-8")
        return Response(
            content=json_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=solution_workflow_{safe_name}_{timestamp}.json"
            }
        )
    except Exception as e:
        logging.exception(f"[SOLUTION_EXPORT] Failed to export workflow data: {e}")
        return JSONResponse({"error": f"Export failed: {str(e)}"}, status_code=500)


@blueprint.get("/api/generic_image/{product_type}")
@login_required
def get_generic_image(request: Request, product_type: str):
    session = get_session(request)

    """Fetch generic product type image with MongoDB caching.

    Strategy:
    1. Check MongoDB cache first
    2. If not found, search external APIs with "generic <product_type>"
    3. Cache the result and return image URL
    """
    import urllib.parse
    from common.services.image_service import fetch_generic_product_image
    from app.core.errors import notify_failure

    try:
        decoded_product_type = urllib.parse.unquote(product_type)

        logging.info(f"[GENERIC_IMAGE] Request for: {decoded_product_type}")

        image_result = fetch_generic_product_image(decoded_product_type)

        if image_result:
            return JSONResponse({
                "success": True,
                "image": image_result,
                "product_type": decoded_product_type,
            }, status_code=200)

        logging.warning(f"[GENERIC_IMAGE] No image found for: {decoded_product_type}")
        notify_failure(
            "Generic Image Not Found",
            f"No image could be found for product category: '{decoded_product_type}'.",
            product_type=decoded_product_type,
        )
        return JSONResponse({
            "success": False,
            "error": "No image found",
            "product_type": decoded_product_type,
        }, status_code=404)

    except Exception as e:
        logging.exception(f"[GENERIC_IMAGE] Error fetching image for {product_type}")
        notify_failure(
            "Generic Image Fetch Error",
            f"Error fetching generic image '{product_type}': {str(e)}",
            product_type=product_type,
            error=str(e),
        )
        return JSONResponse({
            "success": False,
            "error": str(e),
            "product_type": product_type,
        }, status_code=500)


@blueprint.get("/api/image_proxy")
def proxy_image(request: Request):
    """Proxy Azure Blob images through the backend.

    When running locally with Azurite (devstoreaccount1), blob URLs in MongoDB
    point to the cloud storage account (productrecommener2) which blocks public
    access.  This endpoint downloads the blob server-side using the Azure SDK
    and streams the binary data to the browser with appropriate cache headers.

    Query params:
        url  — URL-encoded Azure Blob Storage URL
    """
    import urllib.parse
    import hashlib
    import os
    from fastapi.responses import Response

    blob_url = request.query_params.get("url")
    if not blob_url:
        return JSONResponse({"error": "Missing 'url' query parameter"}, status_code=400)

    # Decode the URL (it was percent-encoded by blob_sas.py)
    blob_url = urllib.parse.unquote(blob_url)

    # Security: only proxy Azure Blob Storage URLs
    if "blob.core.windows.net" not in blob_url:
        return JSONResponse({"error": "Only Azure Blob Storage URLs are allowed"}, status_code=403)

    try:
        # Check local disk cache first to avoid slow cloud downloads
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        cache_dir = os.path.join(backend_dir, ".image_cache")
        os.makedirs(cache_dir, exist_ok=True)

        url_hash = hashlib.md5(blob_url.encode('utf-8')).hexdigest()
        parsed_path = urllib.parse.urlparse(blob_url).path
        ext = os.path.splitext(parsed_path)[1]
        if not ext or ext.lower() not in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']:
            ext = '.png'
        cache_file = os.path.join(cache_dir, f"{url_hash}{ext}")

        if os.path.exists(cache_file):
            logging.info(f"[IMAGE_PROXY] Serving from local disk cache: {blob_url[:50]}")
            with open(cache_file, "rb") as f:
                image_bytes = f.read()
        else:
            from common.infra.azure_blob import azure_blob_manager
            logging.info(f"[IMAGE_PROXY] Downloading: {blob_url[:80]}...")
            image_bytes = azure_blob_manager.download_blob_by_url(blob_url)
            
            try:
                with open(cache_file, "wb") as f:
                    f.write(image_bytes)
                logging.info(f"[IMAGE_PROXY] Saved image to local cache: {cache_file}")
            except Exception as cache_err:
                logging.error(f"[IMAGE_PROXY] Failed to write cache file: {cache_err}")

        # Determine content type from file extension
        lower_url = blob_url.lower()
        if lower_url.endswith(".png"):
            content_type = "image/png"
        elif lower_url.endswith(".jpg") or lower_url.endswith(".jpeg"):
            content_type = "image/jpeg"
        elif lower_url.endswith(".svg"):
            content_type = "image/svg+xml"
        elif lower_url.endswith(".gif"):
            content_type = "image/gif"
        elif lower_url.endswith(".webp"):
            content_type = "image/webp"
        else:
            content_type = "application/octet-stream"

        logging.info(f"[IMAGE_PROXY] Serving {len(image_bytes)} bytes ({content_type})")

        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",  # Cache for 24h
                "X-Proxy-Source": "image_proxy",
            },
        )

    except Exception as e:
        logging.exception(f"[IMAGE_PROXY] Failed to proxy image: {blob_url}")
        return JSONResponse({
            "error": f"Failed to fetch image: {str(e)}",
            "url": blob_url,
        }, status_code=502)
