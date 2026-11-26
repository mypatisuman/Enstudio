"""
LangSmith Hub Synchronization Utility
"""
import glob
import importlib.util
import inspect
import logging
import os
from langchain_core.prompts import ChatPromptTemplate
from langsmith import Client

logger = logging.getLogger("hub_syncer")


def get_prompts_from_module(file_path):
    """Extract all string variables ending in _PROMPT from a python file."""
    prompts = {}
    module_name = os.path.basename(file_path).replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        for name, value in inspect.getmembers(module):
            if name.endswith("_PROMPT") and isinstance(value, str):
                prompts[name] = value
    except Exception as e:
        logger.error("Error loading module %s: %s", file_path, e)
    return prompts


def sync_prompts_to_hub() -> dict:
    """Sync all local prompts (markdown files and Python template vars) to LangSmith Hub.

    Returns execution metrics and logs.
    """
    logger.info("Starting LangSmith Hub synchronization...")
    results = {
        "success": False,
        "synced": [],
        "skipped": [],
        "errors": [],
        "total_attempted": 0,
    }

    # Ensure LangSmith key exists
    if not (os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")):
        results["message"] = "No LangSmith API key configured. Set LANGSMITH_API_KEY env var."
        return results

    try:
        client = Client()
    except Exception as e:
        results["message"] = f"Failed to initialize LangSmith client: {str(e)}"
        return results

    # Get robust backend root path
    backend_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

    # 1. Sync Markdown Prompts
    markdown_pattern = os.path.join(backend_root, "domain", "*", "prompts", "*.md")
    markdown_files = glob.glob(markdown_pattern)
    logger.info("Found %d markdown prompt files to sync.", len(markdown_files))

    for file_path in markdown_files:
        results["total_attempted"] += 1
        prompt_name = os.path.basename(file_path).replace(".md", "").replace("_prompt", "")
        repo_name = f"engenie-{prompt_name}"
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            prompt_template = ChatPromptTemplate.from_template(content)
            client.push_prompt(repo_name, object=prompt_template)
            results["synced"].append({"name": repo_name, "type": "markdown", "file": os.path.basename(file_path)})
            logger.info("Successfully pushed markdown %s as '%s'", file_path, repo_name)
        except Exception as e:
            if "Conflict" in str(e):
                results["skipped"].append({"name": repo_name, "reason": "No changes (Conflict)"})
                logger.info("Skipped markdown prompt %s (no changes)", repo_name)
            else:
                results["errors"].append({"name": repo_name, "error": str(e)})
                logger.error("Error pushing markdown prompt %s: %s", file_path, e)

    # 2. Sync Python Prompts
    python_files_rel = [
        "common/ai/prompts/response/response_prompts.py",
        "common/ai/prompts/templates.py",
        "domain/chat/agents/chat_agent.py",
        "common/ai/rag/chat_rag.py",
        "common/ai/rag/taxonomy_rag.py",
    ]

    for rel_path in python_files_rel:
        file_path = os.path.join(backend_root, rel_path)
        if not os.path.exists(file_path):
            logger.warning("Prompt file %s not found. Skipping.", file_path)
            continue

        prompts = get_prompts_from_module(file_path)
        prefix = "engenie-resp-" if "response" in rel_path else "engenie-tmpl-"

        for name, content in prompts.items():
            results["total_attempted"] += 1
            repo_name = f"{prefix}{name.lower().replace('_prompt', '')}"
            try:
                prompt_template = ChatPromptTemplate.from_template(content)
                client.push_prompt(repo_name, object=prompt_template)
                results["synced"].append({"name": repo_name, "type": "python", "var": name})
                logger.info("Successfully pushed Python prompt %s as '%s'", name, repo_name)
            except Exception as e:
                if "Conflict" in str(e):
                    results["skipped"].append({"name": repo_name, "reason": "No changes (Conflict)"})
                    logger.info("Skipped Python prompt %s (no changes)", repo_name)
                else:
                    results["errors"].append({"name": repo_name, "error": str(e)})
                    logger.error("Error pushing Python prompt %s from %s: %s", name, file_path, e)

    results["success"] = len(results["errors"]) == 0
    results["message"] = (
        f"Prompt sync completed: {len(results['synced'])} synced, "
        f"{len(results['skipped'])} skipped, {len(results['errors'])} errors."
    )
    return results
