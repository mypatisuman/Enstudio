"""Solution Agent — designs high-level control architectures, loop strategies,
and synthesizes comprehensive engineering solutions over the P&ID graph.

Owns inspection tools (to analyze current topology and loops) and authoring
tools (to create or insert solution components).
Prompt: agents/prompts/describe_solution.md
"""
from agents.describe.services import repository as R
from agents.describe.services.grid_service import get_grid_summary
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_SOLUTION_V1

NAME = "solution_agent"

def identify_instruments_and_accessories(pid: str, tags: list[str] | None = None) -> str:
    """Identify required physical and electrical accessories (e.g. manifolds, thermowells, positioners,
    mounting kits, sunshades) and infer complete engineering specifications for P&ID instruments.
    """
    try:
        from domain.solution.services.pid_solution_bridge import enrich_pid_with_solution_bom
        res = enrich_pid_with_solution_bom(session_id=pid, target_tags=tags)
        if not res.get("success"):
            return f"ERROR: {res.get('error', 'Failed to identify accessories')}"

        insts = res.get("instruments", [])
        accs = res.get("accessories", [])

        lines = [f"Successfully identified {len(insts)} instruments and {len(accs)} accessories for P&ID:"]
        for inst in insts[:10]:
            tag = inst.get("tag") or inst.get("productName")
            cat = inst.get("category", "")
            lines.append(f"- **{tag}** ({cat})")

        if accs:
            lines.append("\n**Identified Accessories:**")
            for acc in accs[:15]:
                p_tag = acc.get("instrument_tag") or acc.get("parent_tag") or "General"
                name = acc.get("productName") or acc.get("name") or acc.get("category")
                lines.append(f"- **{name}** (for {p_tag})")

        lines.append(f"\nAll accessories have been decorated onto P&ID nodes and saved to the drawing.")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: Failed to run Solution Agent accessory inference: {str(e)}"

TOOLS = {
    "search_graph": {"fn": R.search_graph, "writes": False},
    "get_node": {"fn": R.get_node, "writes": False},
    "get_connections": {"fn": R.get_connections, "writes": False},
    "get_loops": {"fn": R.get_loops, "writes": False},
    "get_grid": {"fn": lambda pid: get_grid_summary(pid), "writes": False, "doc": "Row/column tile layout of the drawing."},
    "list_hierarchy": {"fn": R.list_hierarchy, "writes": False},
    "get_subsystem_contents": {"fn": R.get_subsystem_contents, "writes": False},
    "next_tag": {"fn": R.next_tag, "writes": False},
    "add_instrument_package": {"fn": R.add_instrument_package, "writes": True},
    "add_nodes": {"fn": R.add_nodes, "writes": True},
    "add_edges": {"fn": R.add_edges, "writes": True},
    "add_junction": {"fn": R.add_junction, "writes": True},
    "insert_between": {"fn": R.insert_between, "writes": True},
    "assign_to_subsystem": {"fn": R.assign_to_subsystem, "writes": True},
    "identify_instruments_and_accessories": {
        "fn": identify_instruments_and_accessories,
        "writes": True,
        "doc": "Identify instruments, infer engineering specifications, and deduce mandatory & optional accessories (manifolds, thermowells, positioners, sunshades) using the AI Solution Engine."
    },
}

_factory = build_tool_agent(NAME, DESCRIBE_SOLUTION_V1, TOOLS, max_steps=20)


def build_solution_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
