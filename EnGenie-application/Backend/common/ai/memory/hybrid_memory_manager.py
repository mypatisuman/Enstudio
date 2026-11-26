import json
import logging
import threading
from typing import Any, List, Dict, Optional

from common.ai.llm import get_lite_llm

logger = logging.getLogger(__name__)

_MONGO_COLLECTION = "user_hybrid_memories"


def _get_collection():
    """Access the MongoDB collection safely."""
    try:
        from common.infra.mongodb_config import get_mongodb_connection
        conn = get_mongodb_connection()
        col = conn["collections"].get(_MONGO_COLLECTION)
        if col is not None:
            return col
        return conn["db"][_MONGO_COLLECTION]
    except Exception as e:
        logger.debug(f"[HYBRID_MEMORY] MongoDB unavailable: {e}")
        return None


def create_default_profile(user_id: Any) -> Dict[str, Any]:
    """Generate a default profile dictionary structure."""
    return {
        "user_id": user_id,
        "interests": [],
        "generated_description": ""
    }


def load_hybrid_memory(user_id: Any) -> Dict[str, Any]:
    """
    Load user's unified dynamic memory profile.
    """
    if not user_id:
        return create_default_profile("anonymous")

    col = _get_collection()
    if col is not None:
        try:
            doc = col.find_one({"user_id": user_id}, {"_id": 0})
            if doc:
                default = create_default_profile(user_id)
                return {**default, **doc}
        except Exception as e:
            logger.warning(f"[HYBRID_MEMORY] Failed to load user profile: {e}")

    return create_default_profile(user_id)


def save_hybrid_memory(user_id: Any, profile: Dict[str, Any]) -> None:
    """
    Save user dynamic memory profile to MongoDB (via background thread).
    """
    if not user_id or user_id == "anonymous":
        return

    updated_profile = dict(profile)
    if "user_id" not in updated_profile:
        updated_profile["user_id"] = user_id

    def _sync():
        col = _get_collection()
        if col is None:
            return
        try:
            col.update_one(
                {"user_id": user_id},
                {"$set": updated_profile},
                upsert=True
            )
            logger.info(f"[HYBRID_MEMORY] Saved user profile for user_id={user_id}")
        except Exception as e:
            logger.error(f"[HYBRID_MEMORY] Background save failed for user_id={user_id}: {e}")

    threading.Thread(target=_sync, daemon=True).start()


def clear_all_user_memories(user_id: Any) -> None:
    """
    Clear all user memories.
    """
    if not user_id:
        return

    def _sync():
        col = _get_collection()
        if col is None:
            return
        try:
            col.delete_one({"user_id": user_id})
            logger.info(f"[HYBRID_MEMORY] Cleared user profile for user_id={user_id}")
        except Exception as e:
            logger.error(f"[HYBRID_MEMORY] Background delete failed for user_id={user_id}: {e}")

    threading.Thread(target=_sync, daemon=True).start()


# Growth/size guards (added 2026-07-31 after a real profile reached 629 interest
# entries / 657K chars of JSON, whose fallback-generated description hit 581K
# chars ≈ 145K tokens and was injected VERBATIM into every intent prompt —
# overflowing Gemma's 128K context and re-creating the "138K intent prompt" bug
# through a second door).
_MAX_PROFILE_INTERESTS = 150     # stored interests kept (most recent)
_DESC_INPUT_MAX_INTERESTS = 30   # interests sent to the description-regen LLM
_DESC_MAX_CHARS = 2000           # stored generated_description hard cap
_INJECTION_MAX_CHARS = 2000      # prompt-injection hard cap (defense in depth)


def update_hybrid_profile(user_id: Any, session_id: str, extracted_interests: List[Dict[str, Any]]) -> None:
    """
    Merges newly extracted product-level interests (vendor + specifications) into the cross-session profile.
    Automatically regenerates the comprehensive natural-language description block.
    """
    if not user_id or user_id == "anonymous" or not extracted_interests:
        return

    profile = load_hybrid_memory(user_id)
    existing_interests = profile.setdefault("interests", [])

    for item in extracted_interests:
        if not isinstance(item, dict):
            continue
        prod_type = item.get("product_type")
        if not prod_type:
            continue

        # Find matching product type in existing profile (case-insensitive)
        match = next(
            (i for i in existing_interests if i.get("product_type", "").lower() == prod_type.lower()),
            None
        )
        
        # Parse incoming vendors list
        incoming_vendors = item.get("vendors", [])
        if isinstance(incoming_vendors, str):
            incoming_vendors = [incoming_vendors]
        
        incoming_specs = item.get("specifications", {})
        if not isinstance(incoming_specs, dict):
            incoming_specs = {}

        if match:
            # Merge vendors uniquely
            existing_vendors = match.setdefault("vendors", [])
            for v in incoming_vendors:
                if v and v.lower() not in [ev.lower() for ev in existing_vendors]:
                    existing_vendors.append(v)
            
            # Merge specs
            existing_specs = match.setdefault("specifications", {})
            existing_specs.update(incoming_specs)
        else:
            # Create new interest entry
            existing_interests.append({
                "product_type": prod_type,
                "vendors": [v for v in incoming_vendors if v],
                "specifications": incoming_specs
            })

    # Cap unbounded growth (most recent entries win)
    if len(existing_interests) > _MAX_PROFILE_INTERESTS:
        removed = len(existing_interests) - _MAX_PROFILE_INTERESTS
        del existing_interests[:removed]
        logger.info(f"[HYBRID_MEMORY] Pruned {removed} oldest interest(s) for user_id={user_id} (cap {_MAX_PROFILE_INTERESTS})")

    # Save immediately, then trigger description updates in the same transaction
    logger.info(f"[HYBRID_MEMORY] Merged {len(extracted_interests)} items for user_id={user_id}. Regenerating description...")
    generate_profile_description(user_id, profile)


DESCRIPTION_PROMPT = """You are a dynamic user interest profiling agent for an industrial procurement assistant.
Your job is to generate a comprehensive, highly coherent natural-language description that summarizes all of the user's preferences, rules, and specifications from their historical searches.

Structured User Interests:
{structured_interests}

Instructions:
1. Compile a single, continuous paragraph summarizing what products the user is interested in.
2. For each product type, explicitly mention ALL preferred vendors (if any) and ALL specification parameters they care about (e.g. pressure ranges, compliance types, accuracy, output signals, calibration).
3. Do NOT make up any specs or vendors not present in the structured data.
4. Keep the text professional, concise, and focused on active procurement rules.
5. If there are no interests, output: "No historical preferences recorded."

Output ONLY the final paragraph. Do not include any greeting, explanation, or markdown formatting outside of the paragraph.
"""


def generate_profile_description(user_id: Any, profile: Dict[str, Any]) -> str:
    """
    Call lite LLM to generate/update a natural-language description from the structured profile.
    """
    interests = profile.get("interests", [])
    if not interests:
        profile["generated_description"] = ""
        save_hybrid_memory(user_id, profile)
        return ""

    try:
        llm = get_lite_llm(temperature=0.1)
        prompt_text = DESCRIPTION_PROMPT.format(
            structured_interests=json.dumps(interests[-_DESC_INPUT_MAX_INTERESTS:], indent=2)
        )
        resp = llm.invoke(prompt_text)
        desc = str(resp.content).strip()[:_DESC_MAX_CHARS]

        # Update and save profile
        profile["generated_description"] = desc
        save_hybrid_memory(user_id, profile)
        logger.info(f"[HYBRID_MEMORY] Successfully regenerated user interest description for user_id={user_id}: {desc[:150]}...")
        return desc
    except Exception as e:
        logger.exception(f"[HYBRID_MEMORY] Failed to generate profile description: {e}")
        # Default description if LLM fails — HARD-CAPPED: iterating the full
        # interests list once produced a 581K-char description that was then
        # injected into every intent prompt.
        desc_lines = []
        for i in interests[-25:]:
            p = i.get("product_type", "Unknown")
            vendors = i.get("vendors", [])
            specs = i.get("specifications", {})

            v_str = f" preferring {', '.join(vendors)}" if vendors else ""
            s_str = f" with specs: {', '.join(f'{k}={v}' for k, v in specs.items())}" if specs else ""
            desc_lines.append(f"Interested in {p}{v_str}{s_str}.")

        desc = " ".join(desc_lines)[:_DESC_MAX_CHARS]
        profile["generated_description"] = desc
        save_hybrid_memory(user_id, profile)
        return desc


def format_profile_for_injection(user_id: Any) -> str:
    """
    Format the dynamic user interest description for prompt injection.
    """
    if not user_id or user_id == "anonymous":
        return ""

    profile = load_hybrid_memory(user_id)
    desc = profile.get("generated_description", "")
    if not desc or desc == "No historical preferences recorded.":
        return ""

    # Defense in depth: never let a runaway stored description blow up the
    # prompt, regardless of how it got into Mongo.
    desc = str(desc)
    if len(desc) > _INJECTION_MAX_CHARS:
        logger.warning(f"[HYBRID_MEMORY] generated_description for user {user_id} is "
                       f"{len(desc):,} chars — truncating to {_INJECTION_MAX_CHARS} for prompt injection")
        desc = desc[:_INJECTION_MAX_CHARS] + "...(truncated)"

    return f"\n[USER PERSONALIZATION RULES]\n{desc}\n[END OF PERSONALIZATION RULES]\n"
