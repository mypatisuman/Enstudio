import json
import logging
import re
import threading
from typing import Any, List, Dict

from common.ai.llm import get_lite_llm
from common.ai.memory.hybrid_memory_manager import update_hybrid_profile
from common.ai.memory.core import format_conversation_for_prompt
from common.ai.memory.search import get_search_history
from common.ai.memory.solution import get_latest_instruments_and_accessories, get_solution_modifications

logger = logging.getLogger(__name__)

# Search-agent and solution-agent turns each spawn a background reflection
# thread for the acting user. Without this guard, a burst of rapid turns
# (e.g. quick follow-up messages) stacks up multiple concurrent reflection
# threads per user, each making 1-2 LLM calls that contend with the user's
# own foreground request for the same rate-limited endpoint/key.
_reflection_in_progress: set[str] = set()
_reflection_lock = threading.Lock()

EXTRACTION_PROMPT = """You are an expert user preference extraction agent.
Your job is to analyze the user's conversation and actions in the current session and extract all product type interests, along with the procurement strategies, business guidelines, preferred vendors, and technical specifications requested or favored by the user.

Session Conversation:
{session_conversation}

Session Search Data:
{search_data}

Session Solution Data:
{solution_data}

Instructions:
1. Extract ALL product types the user searched for, asked about, or modified.
2. For each product type, identify and extract the Preferred Vendors that the user chose most often, explicitly favored, or selected for their final instruments/accessories.
3. For each product type, extract any specific Specifications, Constraints, or Requirements (e.g. pressure ranges, certifications like ATEX, output signals, calibrations) that the user specified.
4. IMPORTANT: Look for and extract any **Procurement Strategies, Purchasing Guidelines, or Business Rules** the user mentions in their chat (e.g., cost-saving mandates, brand standards, safety policies, or vendor allocation rules). Add these rules directly to the "specifications" dictionary under key names like "procurement_strategy" or "purchasing_guideline".
5. Format your output strictly as a JSON list of objects, where each object has these exact keys:
  - "product_type": "Name of Product Type"
  - "vendors": ["VendorName1", "VendorName2"]
  - "specifications": {{"spec_key": "spec_value"}}
  
  Example Output:
  [
    {{
      "product_type": "Pressure Transmitter",
      "vendors": ["Emerson", "ABB"],
      "specifications": {{
        "accuracy": "high",
        "hazardous_area_certification": "ATEX",
        "procurement_strategy": "Prioritize cost-efficiency and regional vendor support"
      }}
    }}
  ]

Output ONLY the JSON list. Do not wrap in markdown or include any explanations outside the JSON block. If no interests are found, output an empty list: [].
"""


def _clean_json_text(text: str) -> str:
    """Helper to remove markdown code fences from JSON output."""
    text = text.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def run_hybrid_memory_reflection(user_id: Any, session_id: str) -> None:
    """
    Background worker that runs reflection on a completed session to extract dynamic interests and specs.
    """
    if not user_id or user_id == "anonymous":
        logger.debug("[HYBRID_MEMORY_AGENT] Skipping reflection: anonymous or empty user_id")
        return

    user_key = str(user_id)
    with _reflection_lock:
        if user_key in _reflection_in_progress:
            logger.info(f"[HYBRID_MEMORY_AGENT] Reflection already in progress for user_id={user_id}; skipping")
            return
        _reflection_in_progress.add(user_key)

    logger.info(f"[HYBRID_MEMORY_AGENT] Starting session profiling for user_id={user_id}, session_id={session_id}")

    try:
        # 1. Load session conversation
        conversation_text = format_conversation_for_prompt(session_id, max_turns=10, include_metadata=True)
        
        # Load and transform search history
        search_history = get_search_history(session_id, max_searches=5)
        search_data = [
            {
                "params": s.get("search_params", {}),
                "timestamp": s.get("timestamp")
            }
            for s in search_history
        ]
        
        # Load solution history
        latest_solution = get_latest_instruments_and_accessories(session_id)
        modifications = get_solution_modifications(session_id)
        solution_data = {
            "latest_instruments": latest_solution.get("instruments", []),
            "latest_accessories": latest_solution.get("accessories", []),
            "modifications": modifications
        }

        # Skip reflection if no session data is present
        if not conversation_text and not search_data and not modifications:
            logger.info(f"[HYBRID_MEMORY_AGENT] Skipping profiling: no active session data found for session_id={session_id}")
            return

        # 2. Call LLM to extract user preference interests
        llm = get_lite_llm(temperature=0.1)
        prompt_text = EXTRACTION_PROMPT.format(
            session_conversation=conversation_text or "No conversation history.",
            search_data=json.dumps(search_data, indent=2) if search_data else "No search history.",
            solution_data=json.dumps(solution_data, indent=2)
        )

        resp = llm.invoke(prompt_text)
        cleaned_text = _clean_json_text(str(resp.content))

        # Find JSON list boundary
        match = re.search(r'\[.*\]', cleaned_text, re.DOTALL)
        if not match:
            logger.warning(f"[HYBRID_MEMORY_AGENT] LLM did not return a valid JSON list: {cleaned_text[:200]}")
            return

        extracted_interests = json.loads(match.group(0))
        if not isinstance(extracted_interests, list):
            logger.warning(f"[HYBRID_MEMORY_AGENT] Extracted interest is not a list structure: {extracted_interests}")
            return

        # 3. Save extracted preferences into the user profile
        update_hybrid_profile(user_id, session_id, extracted_interests)
        logger.info(f"[HYBRID_MEMORY_AGENT] Successfully profiled and updated memories for user_id={user_id}")

    except Exception as e:
        logger.exception(f"[HYBRID_MEMORY_AGENT] Failed preference reflection for user_id={user_id}: {e}")
    finally:
        with _reflection_lock:
            _reflection_in_progress.discard(user_key)
