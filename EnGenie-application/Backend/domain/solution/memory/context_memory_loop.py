"""
Hybrid Context Memory Looping Engine for Solution Workflow
==========================================================
Implements dual-loop context memory synthesis:
1. Multi-Turn Chronological State Accumulation Loop:
   - Anchors initial project genesis requirements (Turn 1).
   - Loops through intermediate turns to capture evolutionary modifications,
     answered clarifications, and component additions.
   - Preserves full active dialog for recent conversation turns.
   - Injects live BOM state and user preference profiles.

2. Workflow Node-to-Node Context Chaining Loop:
   - Records intermediate agent decisions, deduced parameters, and extracted specs
     as each node executes in LangGraph.
   - Chained directly into downstream agents (infer, solution_build, format_results)
     ensuring complete end-to-end reasoning visibility.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from common.ai.memory import (
    format_conversation_for_prompt,
    get_full_conversation_history,
)

logger = logging.getLogger(__name__)

# Configurable token / length ceilings
_MAX_HISTORY_TURNS = int(os.getenv("CONTEXT_MEMORY_MAX_TURNS", "20"))
_MAX_MSG_CHARS = int(os.getenv("CONTEXT_MEMORY_MAX_MSG_CHARS", "20000"))
_MAX_TOTAL_CONTEXT_CHARS = int(os.getenv("CONTEXT_MEMORY_MAX_TOTAL_CHARS", "60000"))


def append_node_execution_context(
    state: Dict[str, Any],
    node_name: str,
    summary: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Appends a node execution record into the workflow's intermediate context trail.
    Enables downstream nodes in the same LangGraph run to see decisions made upstream.
    """
    if "node_execution_trail" not in state or not isinstance(state.get("node_execution_trail"), list):
        state["node_execution_trail"] = []

    trail_entry = {
        "node": node_name,
        "summary": summary,
        "details": details or {},
    }
    state["node_execution_trail"].append(trail_entry)
    logger.debug("[CONTEXT_LOOP] Appended execution trail for node '%s': %s", node_name, summary[:100])


def get_node_execution_trail_summary(state: Dict[str, Any]) -> str:
    """
    Formats the node execution trail into a structured prompt section.
    """
    trail = state.get("node_execution_trail", [])
    if not trail:
        return ""

    lines = ["**Current Workflow Execution Trail:**"]
    for idx, item in enumerate(trail, 1):
        node = item.get("node", "agent")
        summary = item.get("summary", "")
        lines.append(f"  {idx}. [{node}]: {summary}")

    return "\n".join(lines)


def build_looped_conversation_context(
    state: Dict[str, Any],
    session_id: str = "default",
    max_turns: int = _MAX_HISTORY_TURNS,
    max_msg_chars: int = _MAX_MSG_CHARS,
    include_trail: bool = True,
) -> str:
    """
    Chronological Multi-Turn State Accumulator Loop.
    Synthesizes the complete evolution of the project across all conversational turns.
    """
    sections: List[str] = []

    # --------------------------------------------------------------------------
    # 1. User Dynamic Profile Memory
    # --------------------------------------------------------------------------
    user_id = state.get("user_id")
    if user_id:
        try:
            from common.ai.memory.hybrid_memory_manager import format_profile_for_injection
            pref_context = format_profile_for_injection(user_id)
            if pref_context:
                sections.append(f"**User Procurement Profile:**\n{pref_context}")
        except Exception as exc:
            logger.debug("[CONTEXT_LOOP] Error loading dynamic memory profile: %s", exc)

    # --------------------------------------------------------------------------
    # 2. Chronological Conversation Turns (Genesis + Evolution + Recent)
    # --------------------------------------------------------------------------
    full_history = get_full_conversation_history(session_id)
    if full_history and len(full_history) > 0:
        # Separate summary if present
        messages = [m for m in full_history if m.get("role") != "summary"]
        total_turns = len(messages)

        if total_turns == 1:
            # Single turn (Genesis)
            genesis_msg = messages[0]
            sections.append(
                f"**Project Genesis (Initial Prompt):**\n"
                f"{genesis_msg.get('role', 'user').upper()}: {str(genesis_msg.get('content', ''))[:max_msg_chars]}"
            )
        elif total_turns > 1:
            # Turn 1: Project Genesis Anchor
            genesis_msg = messages[0]
            genesis_text = (
                f"**Project Genesis (Turn 1 - Initial Requirements):**\n"
                f"{genesis_msg.get('role', 'user').upper()}: {str(genesis_msg.get('content', ''))[:max_msg_chars]}"
            )
            sections.append(genesis_text)

            # Intermediate turns: Loop and summarize evolutionary changes if history is long
            recent_window_size = min(max_turns, 8)
            if total_turns > recent_window_size + 1:
                intermediate_turns = messages[1:-recent_window_size]
                evolution_lines = ["**Project Evolution & Iterative Turns (Summary):**"]
                for i, turn in enumerate(intermediate_turns, start=2):
                    role = turn.get("role", "user").upper()
                    content = str(turn.get("content", "")).replace("\n", " ").strip()
                    if len(content) > 300:
                        content = content[:300] + "..."
                    evolution_lines.append(f"  - Turn {i} [{role}]: {content}")
                sections.append("\n".join(evolution_lines))
                active_recent_turns = messages[-recent_window_size:]
            else:
                active_recent_turns = messages[1:]

            # Recent Turns: Full fidelity dialog
            recent_lines = ["**Recent Conversation Dialog:**"]
            for turn in active_recent_turns:
                role = turn.get("role", "user").upper()
                content = str(turn.get("content", ""))
                if len(content) > max_msg_chars:
                    content = content[:max_msg_chars] + "...(truncated)"
                line = f"{role}: {content}"
                if turn.get("metadata"):
                    meta = turn["metadata"]
                    meta_summary = []
                    if meta.get("instruments"):
                        meta_summary.append(f"{len(meta['instruments'])} instruments")
                    if meta.get("accessories"):
                        meta_summary.append(f"{len(meta['accessories'])} accessories")
                    if meta_summary:
                        line += f"\n[METADATA STATE: {', '.join(meta_summary)}]"
                recent_lines.append(line)
            sections.append("\n".join(recent_lines))

    # --------------------------------------------------------------------------
    # 3. Frontend Context Memory (UI state, messages, client payload)
    # --------------------------------------------------------------------------
    frontend_context = state.get("context_memory", [])
    if frontend_context and isinstance(frontend_context, list):
        f_lines = []
        for msg in frontend_context[-15:]:
            role = msg.get("role", "system")
            content = msg.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content)
            content = str(content)
            if len(content) > max_msg_chars:
                content = content[:max_msg_chars] + "...(truncated)"
            f_lines.append(f"{role.upper()}: {content}")
        if f_lines:
            sections.append(f"**Frontend Active Context:**\n" + "\n".join(f_lines))

    # --------------------------------------------------------------------------
    # 4. Live BOM & Component Snapshot
    # --------------------------------------------------------------------------
    current_instruments = state.get("instruments", []) or []
    current_accessories = state.get("accessories", []) or []

    if current_instruments or current_accessories:
        bom_lines = [f"**Current Project BOM State ({len(current_instruments)} Instruments, {len(current_accessories)} Accessories):**"]
        for idx, inst in enumerate(current_instruments, 1):
            cat = inst.get("category") or inst.get("product_name") or "Unknown"
            qty = inst.get("quantity", 1)
            specs = inst.get("specifications") or {}
            spec_str = ", ".join([f"{k}={v}" for k, v in list(specs.items())[:6]]) if specs else "No specs"
            bom_lines.append(f"  - Instrument {idx}: {cat} (Qty: {qty}) [{spec_str}]")

        for idx, acc in enumerate(current_accessories, 1):
            name = acc.get("accessory_name") or acc.get("category") or "Accessory"
            qty = acc.get("quantity", 1)
            bom_lines.append(f"  - Accessory {idx}: {name} (Qty: {qty})")

        sections.append("\n".join(bom_lines))

    # --------------------------------------------------------------------------
    # 5. Workflow Node-to-Node Execution Trail
    # --------------------------------------------------------------------------
    if include_trail:
        trail_summary = get_node_execution_trail_summary(state)
        if trail_summary:
            sections.append(trail_summary)

    full_context = "\n\n".join(sections).strip()

    # Safety budget limit
    if len(full_context) > _MAX_TOTAL_CONTEXT_CHARS:
        full_context = full_context[:_MAX_TOTAL_CONTEXT_CHARS] + "\n...(context memory ceiling reached)"

    return full_context or "No previous conversation."
