from common.helpers.azure_session import get_session
"""
Search domain routes.
"""
import logging
import os
import threading
import uuid
from datetime import datetime
import time

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from app.core.security import login_required
from app.core.errors import notify_failure
from app.models.db.base import db
from common.infra.repositories.interaction_log_repository import interaction_logger

from app.services.search_service import check_search_params_completeness, finish_search_agent
from common.helpers.responses import JSONResponse
from common.services import credit_service

blueprint = APIRouter()

vendor_search_tasks: dict = {}
vendor_search_lock = threading.Lock()


def _check_search_params_completeness(*args, **kwargs):
    return check_search_params_completeness(*args, **kwargs)


def _finish_search_agent(
    response: dict,
    search_session_id: str,
    classified_intent: str,
    user_id=None,
    user_session_id=None,
    user_input: str = "",
    request=None,
):
    """Core finalisation logic detached from FastAPI Response generation."""
    from domain.search.services.search_session_context import enrich_response_with_context

    response = enrich_response_with_context(search_session_id, response)
    final_response = finish_search_agent(
        response, search_session_id, classified_intent, user_id, user_session_id, user_input, request
    )
    return JSONResponse(final_response, status_code=200)


@blueprint.post("/api/search-agent")
@login_required
async def search_agent(request: Request):
    # Read the body on the event loop, then run the (entirely synchronous)
    # handler in a worker thread. The handler makes several blocking
    # LLM/agent/workflow calls; running it inline would block the event loop,
    # serialize requests, and stall WS heartbeats. request.json() is the only
    # await in the handler, so this offload is safe.
    try:
        data = await request.json()
    except Exception:
        data = {}
    return await run_in_threadpool(_search_agent_impl, request, data)


@blueprint.get("/api/search-context")
@login_required
async def get_search_context(request: Request):
    """Return persisted search session context (backend SSOT for sidebar specs)."""
    session = get_session(request)
    search_session_id = request.query_params.get("session_id") or request.query_params.get("search_session_id")
    if not search_session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    def _load():
        from domain.search.services.search_session_context import (
            build_context_api_envelope,
            load_search_context,
        )

        ctx = load_search_context(search_session_id)
        if not ctx.mapped_requirements and not ctx.product_type:
            return {"success": False, "message": "No search context for this session.", "sessionId": search_session_id}
        envelope = build_context_api_envelope(ctx)
        envelope["success"] = True
        envelope["sessionId"] = search_session_id
        return envelope

    payload = await run_in_threadpool(_load)
    status = 200 if payload.get("success") else 404
    return JSONResponse(payload, status_code=status)


def _search_agent_impl(request: Request, data: dict):
    session = get_session(request)
    import os
    import re

    from common.ai.llm import get_deterministic_flash
    from common.helpers.progress_tracker import progress_tracker
    from common.services.agentic_integration import run_search_intent

    try:
        user_input = data.get("user_input", "").strip()

        if not user_input:
            return JSONResponse({"error": "user_input is required"}, status_code=400)

        search_session_id = data.get("session_id") or data.get("search_session_id", "default")
        user_id = session.get('user_id')
        user_session_id = data.get("user_session_id")
        current_step = data.get("current_step") or session.get(f'current_step_{search_session_id}', 'initialInput')
        current_intent = data.get("current_intent") or session.get(f'current_intent_{search_session_id}')
        collected_data = data.get("collected_data", {})
        product_type = data.get("product_type") or data.get("productType") or session.get(f'product_type_{search_session_id}', '')
        skip_standard_rag = data.get("skip_standard_rag", False) or data.get("skipStandardRag", False)

        # Auto-prefix product category if provided by tab/solution but omitted from raw spec text
        if product_type and ":" in user_input and not user_input.lower().startswith(product_type.lower()):
            user_input = f"{product_type}, {user_input}"
            logging.info(f"[SEARCH_AGENT] Prepended product_type '{product_type}' to user_input")

        stream_id = data.get("stream_id") or str(uuid.uuid4())
        session[f'stream_id_{search_session_id}'] = stream_id

        from common.helpers.progress_tracker import progress_tracker
        progress_tracker.create_stream(stream_id)

        from common.ai.memory import add_conversation_turn
        add_conversation_turn(
            session_id=search_session_id,
            role="user",
            content=user_input,
            metadata={
                "current_step": current_step,
                "current_intent": current_intent,
                "timestamp": datetime.now().isoformat(),
            }
        )

        intent_result = run_search_intent(
            user_input=user_input,
            current_step=current_step,
            current_intent=current_intent,
            search_session_id=search_session_id,
            user_id=user_id,
            current_page="search",
            product_type=product_type,
        )

        classified_intent = intent_result.get("intent") or intent_result.get("type") or "productRequirements"
        suggested_step = intent_result.get("nextStep") or intent_result.get("next_step")

        logging.info(f"[SEARCH_AGENT] Classified: intent={classified_intent}, suggestedStep={suggested_step}")

        response: dict = {"success": True, "intent": classified_intent}

        if classified_intent == "router_needed":
            response.update({
                "routerNeeded": True,
                "routerCategory": intent_result.get("router_category"),
                "routerTargetPage": intent_result.get("router_target_page"),
                "routerRequiresRouting": intent_result.get("router_requires_routing", False),
                "routerUrl": intent_result.get("router_url", ""),
                "message": intent_result.get("router_message") or intent_result.get("message", ""),
                "nextStep": current_step,
            })
            if intent_result.get("router_requires_routing") and intent_result.get("router_target_page") != "search":
                response.update({
                    "requiresConfirmation": intent_result.get("router_requires_confirmation", True),
                    "confirmationMessage": intent_result.get("router_confirmation_message", ""),
                    "openingMessage": intent_result.get("router_opening_message", ""),
                    "declineMessage": intent_result.get("router_decline_message", ""),
                    "popupBlockedMessage": intent_result.get("router_popup_blocked_message", ""),
                })
            return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        if classified_intent == "reset":
            response.update({"needsConfirmation": True, "message": intent_result.get("message", "Are you sure you want to start over?"), "nextStep": current_step})
            return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        if classified_intent == "reset_confirmed":
            from common.ai.memory import clear_all_session_data, clear_search_memory
            clear_search_memory(search_session_id)
            clear_all_session_data(search_session_id)
            for k in [f'current_step_{search_session_id}', f'current_intent_{search_session_id}', f'product_type_{search_session_id}']:
                session.pop(k, None)
            response.update({"resetComplete": True, "message": intent_result.get("message", "Search reset. What product are you looking for?"), "nextStep": "initialInput"})
            return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        if classified_intent == "reset_cancelled":
            response.update({"message": intent_result.get("message", "OK, let's continue."), "nextStep": current_step})
            return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        if classified_intent == "clarification":
            response.update({"needsClarification": True, "message": intent_result.get("message", "Could you provide more details?"), "nextStep": current_step})
            return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        if classified_intent == "contextual_qna":
            response.update({"message": intent_result.get("message", ""), "nextStep": current_step})
            return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        from domain.search.services.proceed_gate import (
            is_proceed_command,
            resolve_sidebar_chat_action,
            SIDEBAR_EDIT_STEPS,
        )

        target_step = suggested_step or current_step or "initialInput"

        # A prior search must actually exist in this session before treating the
        # turn as a sidebar spec-edit — otherwise (e.g. a stale/mismatched
        # current_step on what is really a fresh tab) this would incorrectly
        # short-circuit into the modification path and fail with a generic
        # "nothing to modify" message instead of running a real product search.
        from common.ai.memory import get_latest_search
        latest_search_precheck = get_latest_search(search_session_id)
        effective_step = current_step if (latest_search_precheck or collected_data) else "initialInput"
        sidebar_action = resolve_sidebar_chat_action(user_input, effective_step)

        if sidebar_action == "proceed":
            logging.info("[SEARCH_AGENT] Proceed gate at %s → finalAnalysis", current_step)
            target_step = "finalAnalysis"
            classified_intent = "workflow"

        elif sidebar_action == "spec_edit":
            from common.ai.memory import format_conversation_for_prompt
            from domain.search.services.search_modification import apply_search_modification

            latest_search = latest_search_precheck
            conversation_context = format_conversation_for_prompt(search_session_id)
            standard_specs_data = session.get(f'standards_specs_{search_session_id}', {})

            mod_result = apply_search_modification(
                session_id=search_session_id,
                user_input=user_input,
                collected_data=collected_data or None,
                conversation_context=conversation_context,
                skip_standard_rag=skip_standard_rag,
                user_id=user_id,
                stream_id=stream_id,
                standard_specs=standard_specs_data,
            )

            response.update(mod_result.to_api_response())
            response["intent"] = "modification"
            if mod_result.merged.get("product_type"):
                session[f'product_type_{search_session_id}'] = mod_result.merged["product_type"]
            session[f'current_step_{search_session_id}'] = "awaitAllSpecs"
            return _finish_search_agent(
                response, search_session_id, "modification", user_id, user_session_id, user_input, request,
            )

        is_refinement = current_step not in ["initialInput", "greeting", None, ""]
        should_auto_update_schema = (
            is_refinement
            and current_step in SIDEBAR_EDIT_STEPS
            and classified_intent in ("modification", "productRequirements")
            and bool(latest_search_precheck or collected_data)
        )
        if (classified_intent == "modification" and bool(latest_search_precheck or collected_data)) or should_auto_update_schema:
            from common.ai.memory import format_conversation_for_prompt
            from domain.search.services.search_modification import apply_search_modification

            latest_search = latest_search_precheck
            conversation_context = format_conversation_for_prompt(search_session_id)
            standard_specs_data = session.get(f'standards_specs_{search_session_id}', {})

            mod_result = apply_search_modification(
                session_id=search_session_id,
                user_input=user_input,
                collected_data=collected_data or None,
                conversation_context=conversation_context,
                skip_standard_rag=skip_standard_rag,
                user_id=user_id,
                stream_id=stream_id,
                standard_specs=standard_specs_data,
            )

            response.update(mod_result.to_api_response())
            response["intent"] = "modification"
            if mod_result.merged.get("product_type"):
                session[f'product_type_{search_session_id}'] = mod_result.merged["product_type"]
            session[f'current_step_{search_session_id}'] = "awaitAllSpecs"

            return _finish_search_agent(response, search_session_id, "modification", user_id, user_session_id, user_input, request)

        logging.info(f"[SEARCH_AGENT] productRequirements → target_step={target_step}")

        if (
            (target_step == "initialInput" or current_step == "initialInput" or classified_intent == "productRequirements")
            and current_step not in SIDEBAR_EDIT_STEPS
        ):
            try:
                from domain.search.agents.search_agent import _quick_extract_product_type
                from domain.search.services.schema_merge import (
                    build_api_schema_payload,
                    run_parallel_requirements_extraction,
                )

                merged = run_parallel_requirements_extraction(
                    user_input,
                    pre_product_type=_quick_extract_product_type(user_input),
                    skip_standard_rag=skip_standard_rag,
                    user_id=user_id,
                    stream_id=stream_id,
                )

                if not merged.get("success"):
                    response.update({"message": merged.get("error", "I couldn't understand the requirements. Please try again."), "nextStep": "initialInput"})
                    return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

                v_product_type = merged.get("product_type", "")

                response.update(build_api_schema_payload(merged))

                if v_product_type:
                    session[f'product_type_{search_session_id}'] = v_product_type

                from domain.search.services.schema_merge import commit_context_after_extraction
                from domain.search.services.search_messages import generate_sidebar_specs_message

                commit_context_after_extraction(
                    search_session_id,
                    merged,
                    workflow_step="awaitAllSpecs",
                    user_input=user_input,
                    assistant_message=generate_sidebar_specs_message(
                        v_product_type,
                        search_session_id,
                        is_modification=False,
                    ) if v_product_type else "",
                )

                if not v_product_type:
                    response.update({"message": "I couldn't detect a specific product type. Could you describe the industrial product you're looking for?", "nextStep": "initialInput"})
                else:
                    response.update({
                        "message": generate_sidebar_specs_message(
                            v_product_type,
                            search_session_id,
                            is_modification=False,
                        ),
                        "nextStep": "awaitAllSpecs",
                    })
            except Exception as ve:
                logging.exception(f"[SEARCH_AGENT] Validation error: {ve}")
                err_str = str(ve).lower()
                if "connection" in err_str or "timeout" in err_str:
                    msg = "I'm having trouble connecting to my database. Please try again in a moment."
                elif "quota" in err_str or "rate limit" in err_str:
                    msg = "I've reached my processing limit. Please wait a few seconds and try again."
                else:
                    msg = f"I had trouble processing those requirements ({type(ve).__name__}). Could you try rephrasing?"
                response.update({"message": msg, "nextStep": "initialInput"})

            return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        HEAVY_ANALYSIS_STEPS = {"analyze", "search_vendors", "find_vendors", "vendorAnalysis", "vendor_analysis"}
        if target_step in HEAVY_ANALYSIS_STEPS or classified_intent in ["analyze", "search"]:
            from domain.search.workflows.search_workflow import run_search_workflow
            from common.helpers.response_formatter import standardize_and_convert_response

            workflow_kwargs = {
                "user_input": user_input,
                "session_id": search_session_id,
                "search_session_id": search_session_id,
                "user_session_id": user_session_id,
                "user_id": user_id,
                "stream_id": stream_id,
                "enable_streaming": True,
                "workflow_step": current_step,
                "current_intent": classified_intent,
            }

            logging.info(f"[SEARCH_AGENT] Starting asynchronous heavy analysis for stream: {stream_id}")
            from common.services.job_dispatch import dispatch_job

            credit_gate = credit_service.check_workflow_allowed(user_id, "search")
            if not credit_gate.get("allowed", True):
                return JSONResponse({
                    "error": "Insufficient credits",
                    "message": credit_gate.get("reason") or "You do not have enough credits to run this search.",
                    "required_credits": credit_gate.get("cost"),
                    "balance": credit_gate.get("balance"),
                }, status_code=402)
            credit_service.register_workflow_run(stream_id, user_id, "search", session_id=search_session_id)

            def _background_search_worker():
                try:
                    from common.monitoring.benchmarking import live
                    with live.capture("search", user_input=user_input, user_id=user_id):
                        res = run_search_workflow(**workflow_kwargs)
                    standardized_res = standardize_and_convert_response(res)
                    if res.get("success", True) is False and res.get("error"):
                        progress_tracker.emit(stream_id, "error", standardized_res)
                        credit_service.settle_workflow_run(stream_id, success=False)
                    else:
                        progress_tracker.emit(stream_id, "result", standardized_res)
                        credit_service.settle_workflow_run(stream_id, success=True)
                except Exception as e:
                    logging.exception(f"[SEARCH_AGENT] Heavy analysis failed: {e}")
                    progress_tracker.emit(stream_id, "error", {"message": str(e), "success": False})
                    credit_service.settle_workflow_run(stream_id, success=False)
                finally:
                    progress_tracker.close_stream(stream_id, reason="search-heavy-analysis-finished")

            # Hands off to a separate worker when WORKER_URL is configured
            # (the worker calls back to /api/callbacks/{stream_id}); otherwise
            # runs the job in-process via the runner above.
            dispatch_job(
                stream_id=stream_id,
                job_type="search",
                job_payload=workflow_kwargs,
                in_process_runner=_background_search_worker,
            )

            return JSONResponse({
                "success": True,
                "status": "processing",
                "stream_id": stream_id,
                "streamId": stream_id,
                "nextStep": "finalAnalysis",
            }, status_code=202)

        if classified_intent == "workflow":
            from common.ai.memory import get_latest_search as _get_latest, load_interim_state as _load_interim
            from domain.search.services.search_messages import generate_sidebar_specs_message

            _next_step = intent_result.get("nextStep") or suggested_step or current_step
            logging.info(f"[SEARCH_AGENT] Workflow navigation: {current_step} -> {_next_step}")

            _latest = _get_latest(search_session_id)
            _prev_meta = _latest.get("metadata", {}) if _latest else {}
            pt = product_type or _prev_meta.get("product_type", "")

            _LEGACY_SPEC_STEPS = {
                "awaitMissingInfo",
                "awaitOptionalSpecs",
                "awaitAdditionalAndLatestSpecs",
                "awaitAdvancedSpecs",
                "initialInput",
            }
            if _next_step in _LEGACY_SPEC_STEPS:
                logging.info(f"[SEARCH_AGENT] Legacy workflow step '{_next_step}' mapped to awaitAllSpecs")
                _next_step = "awaitAllSpecs"

            if _next_step == "showSummary":
                logging.info("[SEARCH_AGENT] Legacy showSummary mapped to finalAnalysis")
                _next_step = "finalAnalysis"

            if _next_step == "finalAnalysis":
                if is_proceed_command(user_input):
                    target_step = "finalAnalysis"
                    logging.info("[SEARCH_AGENT] Workflow confirmed finalAnalysis — falling through to execution block.")
                else:
                    logging.info(
                        "[SEARCH_AGENT] Workflow suggested finalAnalysis without proceed command — staying at awaitAllSpecs",
                    )
                    _next_step = "awaitAllSpecs"

            if target_step == "finalAnalysis":
                pass  # fall through to finalAnalysis execution block below
            else:
                _saved = _load_interim(search_session_id) or {}
                response["message"] = generate_sidebar_specs_message(
                    pt or "product",
                    search_session_id,
                    is_modification=False,
                )
                response["nextStep"] = "awaitAllSpecs"
                response["missingMandatoryFields"] = _saved.get("missing_mandatory_fields", [])
                response["missingOptionalFields"] = _saved.get("missing_optional_fields", [])
                response["advancedSpecs"] = _saved.get("advanced_specs", [])
                return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

        if target_step == "finalAnalysis":
            if current_step in SIDEBAR_EDIT_STEPS and not is_proceed_command(user_input):
                logging.warning(
                    "[SEARCH_AGENT] finalAnalysis blocked — input is not a proceed command; routing to spec edit",
                )
                from common.ai.memory import format_conversation_for_prompt
                from domain.search.services.search_modification import apply_search_modification

                mod_result = apply_search_modification(
                    session_id=search_session_id,
                    user_input=user_input,
                    collected_data=collected_data or None,
                    conversation_context=format_conversation_for_prompt(search_session_id),
                    skip_standard_rag=skip_standard_rag,
                    user_id=user_id,
                    stream_id=stream_id,
                    standard_specs=session.get(f'standards_specs_{search_session_id}', {}),
                )
                response.update(mod_result.to_api_response())
                response["intent"] = "modification"
                session[f'current_step_{search_session_id}'] = "awaitAllSpecs"
                return _finish_search_agent(
                    response, search_session_id, "modification", user_id, user_session_id, user_input, request,
                )

            import json as _json
            from domain.search.services.search_session_context import (
                ContextEvent,
                commit_search_context,
                load_search_context,
            )

            ctx = load_search_context(search_session_id)
            final_product_type = product_type or ctx.product_type
            mapped_requirements = ctx.mapped_requirements

            if not mapped_requirements:
                logging.warning("[SEARCH_AGENT] proceed with empty context — falling back to user input")
                _user_input_str = user_input
                _structured_requirements_str = ""
            else:
                commit_search_context(ctx, ContextEvent.PROCEED, user_input=user_input, assistant_message=user_input)
                _clean_requirements = {k: v for k, v in mapped_requirements.items() if k != "unmapped_specs"}
                _structured_requirements_str = _json.dumps(_clean_requirements)
                _user_input_str = (
                    f"Product Type: {final_product_type}. {_structured_requirements_str}"
                    if final_product_type
                    else user_input
                )

            from domain.search.workflows.search_workflow import run_search_workflow
            from common.helpers.response_formatter import standardize_and_convert_response
            from common.services.job_dispatch import dispatch_job

            logging.info(f"[SEARCH_AGENT] Starting asynchronous finalAnalysis for stream: {stream_id}")

            langgraph_seed = ctx.to_langgraph_state() if mapped_requirements else {}
            workflow_kwargs = {
                "user_input": _user_input_str,
                "session_id": search_session_id,
                "search_session_id": search_session_id,
                "user_session_id": user_session_id,
                "user_id": user_id,
                "stream_id": stream_id,
                "enable_streaming": True,
                "detected_product_type": final_product_type or langgraph_seed.get("detected_product_type", ""),
                "structured_requirements": _structured_requirements_str,
                "workflow_step": "finalAnalysis",
                "current_intent": "workflow",
                "skip_reextract": bool(mapped_requirements),
                "mapped_requirements": langgraph_seed.get("mapped_requirements", mapped_requirements),
                "detected_schema": langgraph_seed.get("detected_schema", ctx.detected_schema),
                "provided_requirements": langgraph_seed.get("provided_requirements", ctx.provided_requirements),
                "unmapped_specs": langgraph_seed.get("unmapped_specs", ctx.unmapped_specs),
                "specified_vendors": langgraph_seed.get("specified_vendors", ctx.specified_vendors),
                "specified_model_families": langgraph_seed.get(
                    "specified_model_families", ctx.specified_model_families,
                ),
                "applicable_standards": langgraph_seed.get("applicable_standards", ctx.applicable_standards),
                "schema_source": langgraph_seed.get("schema_source", ctx.schema_source),
                "change_log": ctx.change_log,
                "context_version": ctx.version,
                "proceed_confirmed": True,
            }

            credit_gate = credit_service.check_workflow_allowed(user_id, "search")
            if not credit_gate.get("allowed", True):
                return JSONResponse({
                    "error": "Insufficient credits",
                    "message": credit_gate.get("reason") or "You do not have enough credits to run this search.",
                    "required_credits": credit_gate.get("cost"),
                    "balance": credit_gate.get("balance"),
                }, status_code=402)
            credit_service.register_workflow_run(stream_id, user_id, "search", session_id=search_session_id)

            def _background_search_worker():
                try:
                    from common.monitoring.benchmarking import live
                    with live.capture("search", user_input=_user_input_str, user_id=user_id):
                        _res = run_search_workflow(**workflow_kwargs)
                    standardized_res = standardize_and_convert_response(_res)
                    if _res.get("success", True) is False and _res.get("error"):
                        progress_tracker.emit(stream_id, "error", standardized_res)
                        credit_service.settle_workflow_run(stream_id, success=False)
                    else:
                        from common.helpers.notifications import notify_task_completion
                        pt_name = workflow_kwargs.get("product_type") or "Product"
                        notify_task_completion(
                            title=f"{pt_name} Search Complete",
                            message=f"Vendor analysis for {pt_name} has finished successfully with matched products.",
                            user_id=user_id,
                            page="search",
                            task_type="vendor_search",
                            stream_id=stream_id,
                        )
                        progress_tracker.emit(stream_id, "task_complete", {
                            "title": f"{pt_name} Search Complete",
                            "message": f"Vendor analysis for {pt_name} is ready.",
                            "sound": True,
                            "task_type": "search",
                            "stream_id": stream_id,
                        })
                        progress_tracker.emit(stream_id, "result", standardized_res)
                        credit_service.settle_workflow_run(stream_id, success=True)
                except Exception as _e:
                    logging.exception(f"[SEARCH_AGENT] finalAnalysis failed: {_e}")
                    progress_tracker.emit(stream_id, "error", {"message": str(_e), "success": False})
                    credit_service.settle_workflow_run(stream_id, success=False)
                finally:
                    progress_tracker.close_stream(stream_id, reason="search-final-analysis-finished")

            dispatch_job(
                stream_id=stream_id,
                job_type="search",
                job_payload=workflow_kwargs,
                in_process_runner=_background_search_worker,
            )

            return JSONResponse({
                "success": True,
                "status": "processing",
                "stream_id": stream_id,
                "streamId": stream_id,
                "nextStep": "finalAnalysis",
            }, status_code=202)

        response.update({"message": intent_result.get("message") or "Let's continue.", "nextStep": target_step})
        return _finish_search_agent(response, search_session_id, classified_intent, user_id, user_session_id, user_input, request)

    except Exception as e:
        logging.exception("[SEARCH_AGENT] Request handling failed")
        notify_failure("Search Agent Processing", str(e), page="search", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/api/clear-session-memory")
async def clear_session_memory(request: Request):
    session = get_session(request)
    try:
        from common.ai.memory import clear_all_session_data
        try:
            data = await request.json()
        except Exception:
            data = {}
        session_id = data.get("session_id", "default")
        clear_all_session_data(session_id)
        logging.info(f"[API] Cleared session memory for: {session_id}")
        return JSONResponse({"success": True, "message": "Session memory cleared successfully"})
    except Exception as e:
        logging.exception(f"[API] Failed to clear session memory: {e}")
        return JSONResponse({"success": False, "error": str(e), "message": "Failed to clear session memory"}, status_code=500)


@blueprint.get("/api/search-status/{stream_id}")
@login_required
async def search_status(request: Request, stream_id: str):
    session = get_session(request)
    from common.helpers.progress_tracker import progress_tracker
    events = progress_tracker.consume_events(stream_id)
    final_result = progress_tracker.get_final_result(stream_id)
    if final_result and not any(e.get("type") in ("result", "error") for e in events):
        events.append(final_result)
    if not events:
        return JSONResponse({"status": "waiting", "events": []}, status_code=200)
    return JSONResponse({"status": "events", "events": events}, status_code=200)


@blueprint.post("/api/get_analysis_product_images")
@login_required
async def get_analysis_product_images(request: Request):
    session = get_session(request)
    import concurrent.futures
    from common.services.image_service import fetch_product_images_with_fallback_sync, fetch_vendor_logo_sync

    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        vendor = data.get("vendor", "")
        product_type = data.get("product_type", "")
        product_name = data.get("product_name", "")
        model_families = data.get("model_families", [])

        if not vendor:
            return JSONResponse({"error": "Vendor name is required"}, status_code=400)

        primary_family = str(model_families[0]).strip() if isinstance(model_families, list) and model_families else None
        base_name_for_search = primary_family or product_name

        search_combinations = []
        if base_name_for_search and product_type:
            search_combinations.append({"query": f"{vendor} {base_name_for_search} {product_type}", "priority": 1})
        if base_name_for_search:
            search_combinations.append({"query": f"{vendor} {base_name_for_search}", "priority": 2})
        if product_type:
            search_combinations.append({"query": f"{vendor} {product_type}", "priority": 3})

        max_workers = max(len(search_combinations) + 1, 10)
        all_images: list = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            logo_future = executor.submit(fetch_vendor_logo_sync, vendor)
            futures = {
                executor.submit(fetch_product_images_with_fallback_sync, vendor_name=vendor, product_name=None, model_family=base_name_for_search or None, product_type=product_type or None): info
                for info in search_combinations
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result(timeout=30)
                    search_info = futures[future]
                    if isinstance(result, tuple):
                        imgs, source = result
                        if imgs and isinstance(imgs, list):
                            for img in imgs:
                                img["search_type"] = search_info["type"] if "type" in search_info else "unknown"
                                img["search_priority"] = search_info["priority"]
                            all_images.extend(imgs)
                    elif isinstance(result, list):
                        for img in result:
                            if isinstance(img, dict):
                                img["search_type"] = search_info["type"] if "type" in search_info else "unknown"
                                img["search_priority"] = search_info["priority"]
                        all_images.extend(result)
                except Exception as img_err:
                    logging.warning(f"[IMAGES] Image fetch failed: {img_err}")

        vendor_logo = None
        try:
            vendor_logo = logo_future.result(timeout=15)
        except Exception:
            pass

        seen_urls: set = set()
        unique_images = []
        for img in all_images:
            url = img.get("url") or img.get("imageUrl", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_images.append(img)

        def image_quality_score(img):
            score = 0
            score += (5 - img.get("search_priority", 5)) * 10
            source = img.get("source", "")
            if source == "azure_blob":
                score += 20
            elif source == "search_engine":
                score += 5
            title = img.get("title", "").lower()
            if product_name and product_name.lower() in title:
                score += 8
            models = model_families if isinstance(model_families, list) else [model_families]
            for model in models:
                if model and str(model).lower() in title:
                    score += 6
                    break
            return score

        unique_images.sort(key=image_quality_score, reverse=True)
        top_image = unique_images[0] if unique_images else None

        return JSONResponse({"success": True, "vendor": vendor, "product_type": product_type, "product_name": product_name, "model_families": model_families, "top_image": top_image, "vendor_logo": vendor_logo, "all_images": unique_images[:10], "total_found": len(unique_images), "unique_count": len(unique_images), "best_count": 1 if top_image else 0})

    except Exception as e:
        logging.exception("[IMAGES] Product image fetch failed")
        notify_failure("Search Product Images Fetch", str(e), page="search", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.get("/api/get-price-review")
@login_required
async def api_get_price_review(request: Request):
    session = get_session(request)
    try:
        from common.services.price_service import fetch_price_and_reviews

        product_name = request.query_params.get('productName')
        if not product_name:
            return JSONResponse({"error": "productName is required"}, status_code=400)

        result_data = fetch_price_and_reviews(
            product_name=product_name,
            vendor_name=request.query_params.get('vendorName'),
            model_family=request.query_params.get('modelFamily'),
            sub_model=request.query_params.get('subModel'),
            product_type=request.query_params.get('productType'),
            user_location=request.query_params.get('userLocation'),
        )

        if result_data.get("location_attempted") and not result_data.get("location_used"):
            logging.info(f"[PRICE_FALLBACK] No results in '{result_data['location_attempted']}' for '{product_name}'. Returned global results.")

        results = result_data.get("results", [])
        total_results = len(results)
        limited_results = results[:10]

        if total_results > 10:
            logging.info(f"[PRICE_LIMIT] Limiting '{product_name}': {len(limited_results)} of {total_results}")

        return JSONResponse({"productName": product_name, "results": limited_results, "totalResults": total_results}, status_code=200)
    except Exception as e:
        logging.exception("[PRICE_REVIEW] Failed to fetch price and reviews")
        notify_failure("Search Price & Review Fetch", str(e), page="search", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to fetch price and review data: " + str(e)}, status_code=500)


@blueprint.post("/api/feedback")
@login_required
async def handle_feedback(request: Request):
    session = get_session(request)
    try:
        from app.models.db.user_model import User
        from app.services.feedback_service import process_and_store_feedback

        try:
            data = await request.json()
        except Exception:
            data = {}
        feedback_type = data.get("feedbackType")
        comment = data.get("comment", "")
        item_metadata = data.get("itemMetadata", {})
        project_id = data.get("projectId") or session.get('current_project_id')
        log_user_query = session.get('log_user_query', '')

        current_user = db.session.get(User, session['user_id'])
        if not current_user:
            return JSONResponse({"error": "Authenticated user not found."}, status_code=404)

        result_dict = process_and_store_feedback(
            user_id=str(session.get('user_id')),
            username=current_user.username,
            feedback_type=feedback_type,
            comment=comment,
            item_metadata=item_metadata,
            project_id=project_id,
            log_user_query=log_user_query,
        )

        if "error" in result_dict:
            return JSONResponse({"error": result_dict["error"]}, status_code=503 if "ready" in result_dict["error"] else 400)

        return JSONResponse({"response": result_dict.get("response")}, status_code=200)

    except Exception as e:
        logging.exception("[FEEDBACK] Feedback handling failed.")
        notify_failure("Search Feedback Processing", str(e), page="search", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to process feedback: " + str(e)}, status_code=500)


# Field description L1 cache and lock
_field_desc_cache = {}
_field_desc_lock = threading.Lock()
_field_desc_access: dict[str, float] = {}
_FIELD_DESC_CACHE_MAX_ENTRIES = int(os.environ.get("FIELD_DESC_CACHE_MAX_ENTRIES", "2000"))
_FIELD_DESC_CACHE_IDLE_TTL_SECONDS = int(os.environ.get("FIELD_DESC_CACHE_IDLE_TTL_SECONDS", str(24 * 3600)))


def evict_stale_field_desc_cache() -> int:
    """Evict idle-expired entries first; if still over the cap, evict the
    oldest-accessed entries until back under _FIELD_DESC_CACHE_MAX_ENTRIES.
    Returns count evicted. Called from the periodic memory sweep
    (common/ai/memory/maintenance.py) — not session-scoped (keyed by
    field+product name), managed independently of session eviction.
    """
    now = time.time()
    evicted = 0
    with _field_desc_lock:
        stale = [k for k, t in _field_desc_access.items() if now - t > _FIELD_DESC_CACHE_IDLE_TTL_SECONDS]
        for k in stale:
            _field_desc_cache.pop(k, None)
            _field_desc_access.pop(k, None)
            evicted += 1

        if len(_field_desc_cache) > _FIELD_DESC_CACHE_MAX_ENTRIES:
            overflow = len(_field_desc_cache) - _FIELD_DESC_CACHE_MAX_ENTRIES
            oldest = sorted(_field_desc_access.items(), key=lambda kv: kv[1])[:overflow]
            for k, _ in oldest:
                _field_desc_cache.pop(k, None)
                _field_desc_access.pop(k, None)
                evicted += 1

    if evicted:
        logging.info(f"[FIELD_DESCRIPTION] Evicted {evicted} stale/overflow cache entries")
    return evicted

# Bound concurrent field-description LLM calls — the frontend fetches ~30 fields
# in parallel; this caps how many hit the LLM at once. Waiters park on the event
# loop (cheap), not on threadpool threads. Lazily created on the running loop.
import asyncio as _asyncio
_field_desc_sem: "_asyncio.Semaphore | None" = None


def _field_desc_semaphore() -> "_asyncio.Semaphore":
    global _field_desc_sem
    if _field_desc_sem is None:
        _field_desc_sem = _asyncio.Semaphore(8)
    return _field_desc_sem


async def _resolve_field_description(field: str, product_type: str, llm) -> str:
    """Resolve a single field's description via L1/L2 cache, falling back to the LLM."""
    field_normalized = field.lower().strip()
    product_normalized = product_type.lower().strip()
    cache_key = f"{field_normalized}|{product_normalized}"

    # ── 1. CHECK L1 MEMORY CACHE ──
    with _field_desc_lock:
        cached_desc = _field_desc_cache.get(cache_key)
        if cached_desc:
            _field_desc_access[cache_key] = time.time()
            logging.info(f"[FIELD_DESCRIPTION] L1 Cache HIT for key: {cache_key}")
            return cached_desc

    # ── 2. CHECK L2 MONGODB CACHE ──
    desc_collection = None
    try:
        from common.infra.mongodb_config import get_mongodb_connection
        conn = get_mongodb_connection()
        desc_collection = conn['database']['field_descriptions']

        db_entry = desc_collection.find_one({
            "field_normalized": field_normalized,
            "product_normalized": product_normalized
        })
        if db_entry:
            description = db_entry.get("description")
            if description:
                logging.info(f"[FIELD_DESCRIPTION] L2 (MongoDB) Cache HIT for key: {cache_key}")
                with _field_desc_lock:
                    _field_desc_cache[cache_key] = description
                    _field_desc_access[cache_key] = time.time()
                return description
    except Exception as db_err:
        logging.error(f"[FIELD_DESCRIPTION] L2 MongoDB cache query failed: {db_err}")

    # ── 3. CACHE MISS: INVOKE LLM ──
    logging.info(f"[FIELD_DESCRIPTION] Cache MISS for key: {cache_key}. Invoking LLM...")
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    description_prompt = f"""You are a technical assistant for industrial automation products.

For the field '{field}' in the context of {product_type} products:

1. Write a clear, concise description in 1-2 lines explaining what this field means.
2. Then provide 2-3 realistic sample values.

Format your response EXACTLY like this (no extra text):
<1-2 line description>
Examples: <example1>, <example2>, <example3>"""

    prompt = ChatPromptTemplate.from_template(description_prompt)
    chain = prompt | llm | StrOutputParser()
    # Offload the blocking LLM call to a worker thread, bounded by a
    # semaphore so a burst of misses doesn't hit the LLM all at once.
    # Without the offload the async endpoint would serialize every
    # call on the event-loop thread and stall WS heartbeats / other routes.
    async with _field_desc_semaphore():
        description_response = await run_in_threadpool(
            chain.invoke, {"field": field, "product_type": product_type}
        )

    # ── 4. SAVE TO CACHES ──
    with _field_desc_lock:
        _field_desc_cache[cache_key] = description_response
        _field_desc_access[cache_key] = time.time()

    try:
        if desc_collection is None:
            from common.infra.mongodb_config import get_mongodb_connection
            desc_collection = get_mongodb_connection()['database']['field_descriptions']
        desc_collection.update_one(
            {
                "field_normalized": field_normalized,
                "product_normalized": product_normalized
            },
            {
                "$set": {
                    "field": field,
                    "product_type": product_type,
                    "description": description_response,
                    "timestamp": datetime.utcnow()
                }
            },
            upsert=True
        )
        logging.info(f"[FIELD_DESCRIPTION] Saved new description to L2 (MongoDB) for key: {cache_key}")
    except Exception as db_save_err:
        logging.error(f"[FIELD_DESCRIPTION] Failed to save description to L2: {db_save_err}")

    return description_response


@blueprint.post("/api/get_field_description")
@login_required
async def api_get_field_description(request: Request):
    session = get_session(request)
    try:
        from common.ai.llm.manager import get_lite_llm
        llm = get_lite_llm(temperature=0.1)
    except Exception as e:
        logging.error(f"[FIELD_DESCRIPTION] Failed to initialize LLM: {e}")
        return JSONResponse({"error": "Backend is not ready. LLM initialization failed."}, status_code=503)

    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        field = data.get("field", "").strip()
        product_type = data.get("product_type", "general").strip()

        if not field:
            return JSONResponse({"error": "Missing 'field' parameter."}, status_code=400)

        description_response = await _resolve_field_description(field, product_type, llm)
        return JSONResponse({"description": description_response}, status_code=200)

    except Exception as e:
        logging.exception("Failed to get field description from LLM.")
        notify_failure("Search Field Description", str(e), page="search", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to get field description: " + str(e)}, status_code=500)


@blueprint.post("/api/get_field_descriptions_batch")
@login_required
async def api_get_field_descriptions_batch(request: Request):
    """
    Batched counterpart to /api/get_field_description. Accepts up to ~200 fields
    in one request so a schema render doesn't fan out into dozens of individual
    HTTP round-trips (each of which pays connection/auth/session overhead even
    when the answer is a cache hit with no LLM involved).
    """
    session = get_session(request)
    try:
        from common.ai.llm.manager import get_lite_llm
        llm = get_lite_llm(temperature=0.1)
    except Exception as e:
        logging.error(f"[FIELD_DESCRIPTION] Failed to initialize LLM: {e}")
        return JSONResponse({"error": "Backend is not ready. LLM initialization failed."}, status_code=503)

    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        product_type = data.get("product_type", "general").strip()
        fields = data.get("fields", [])
        if not isinstance(fields, list) or not fields:
            return JSONResponse({"error": "Missing or empty 'fields' list parameter."}, status_code=400)

        # Bound batch size defensively; the sidebar renders on the order of
        # tens to low hundreds of fields per product schema.
        fields = [str(f).strip() for f in fields if str(f).strip()][:200]

        results = await _asyncio.gather(
            *(_resolve_field_description(field, product_type, llm) for field in fields),
            return_exceptions=True,
        )

        descriptions: dict[str, str] = {}
        for field, result in zip(fields, results):
            if isinstance(result, Exception):
                logging.error(f"[FIELD_DESCRIPTION] Batch item failed for field='{field}': {result}")
                descriptions[field] = "No description available"
            else:
                descriptions[field] = result

        return JSONResponse({"descriptions": descriptions}, status_code=200)

    except Exception as e:
        logging.exception("Failed to get batched field descriptions from LLM.")
        notify_failure("Search Field Description Batch", str(e), page="search", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to get field descriptions: " + str(e)}, status_code=500)
