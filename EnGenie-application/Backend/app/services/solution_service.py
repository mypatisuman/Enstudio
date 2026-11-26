"""
Solution service layer — app-level orchestration for the solution/deep-instrument-analysis workflow.

Delegates to domain/solution/agents/ and common/services/agentic_integration.py.
Route handlers import from here to stay thin HTTP-only layers.
"""
import logging

from common.infra.repositories.interaction_log_repository import interaction_logger


def run_solution_agent(
    user_input: str,
    stream_id: str,
    user_id=None,
    data: dict = None,
) -> dict:
    """
    Run the solution agent synchronously, emitting progress events to Redis.
    Must be called via asyncio.to_thread() from the route handler so the HTTP
    connection stays open (keeping the Azure Functions process alive) while the
    sync LLM work runs without blocking the event loop.
    Returns the final result dict.
    """
    from common.services.agentic_integration import run_project_intent
    from common.helpers.progress_tracker import progress_tracker
    from app.core.errors import notify_failure

    data = data or {}

    try:
        compressed_input = user_input
        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            from common.ai.llm import get_lite_llm

            lite_llm = get_lite_llm(temperature=0.1)
            preview_chain = (
                ChatPromptTemplate.from_template(
                    "Provide a short preview (<=150 words) answering the user's input.\n\nUser Input:\n{text}\n\nPreview:"
                )
                | lite_llm
                | StrOutputParser()
            )
            try:
                preview_text = preview_chain.invoke({"text": user_input})
                progress_tracker.emit(stream_id, "preview", {"message": "Preview ready", "preview": preview_text, "progress": 5})
            except Exception:
                pass

            compress_chain = (
                ChatPromptTemplate.from_template(
                    "Compress the following user input preserving all intent (<=2000 chars).\n\nInput:\n{text}\n\nCompressed:"
                )
                | lite_llm
                | StrOutputParser()
            )
            try:
                candidate = compress_chain.invoke({"text": user_input})
                if candidate and candidate.strip():
                    compressed_input = candidate
            except Exception:
                pass
        except Exception:
            pass

        result = run_project_intent(
            user_input=compressed_input,
            current_instruments=data.get("current_instruments"),
            current_accessories=data.get("current_accessories"),
            awaiting_single_item_confirmation=data.get("awaiting_single_item_confirmation", False),
            awaiting_holistic_confirmation=data.get("awaiting_holistic_confirmation") or data.get("awaiting_comprehensiveness_confirmation", False),
            search_session_id=data.get("search_session_id") or data.get("user_session_id"),
            user_session_id=data.get("user_session_id"),
            user_id=user_id,
            context_memory=data.get("context_memory", []),
            stream_id=stream_id,
            enable_streaming=True,
            skip_standards=data.get("skip_standards", False),
        )

        result["success"] = True
        progress_tracker.emit(stream_id, "result", result)

        try:
            interaction_logger.log_interaction(
                user_id=str(user_id) if user_id else "anonymous",
                session_id=data.get("user_session_id", stream_id),
                user_input=user_input,
                response=f"Intent: {result.get('intent')} | {len(result.get('instruments', []))} instruments, {len(result.get('accessories', []))} accessories",
                metadata={"agent_type": "solution", "stream_id": stream_id, "intent": result.get("intent"), "success": True},
                interaction_type="solution",
            )
        except Exception as log_err:
            logging.warning(f"[SOLUTION_SERVICE] Interaction log failed: {log_err}")

        return result

    except Exception as e:
        logging.exception(f"[SOLUTION_SERVICE] Processing failed for stream: {stream_id}")
        progress_tracker.emit(stream_id, "error", {"error": str(e), "message": "Failed to process request"})
        notify_failure("Solution Agent Processing", str(e), page="solution", user_id=user_id)
        return {"success": False, "error": str(e), "message": "Failed to process request"}
    finally:
        progress_tracker.close_stream(stream_id, reason="solution-service-finished")
