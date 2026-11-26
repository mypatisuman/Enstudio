"""
Prompts Module

Centralized LLM prompts for the agentic system.
Organized by tool name for easy maintenance.
"""

# Note: Router Classifier prompts have been moved to orchestrator/agents/router_classifier_agent.py
# and are loaded from .md files in orchestrator/prompts/

# Advanced Specs Discovery Tool prompts removed - now using agent prompts
# See: prompts/validation_agent/prompts.py for ADVANCED_SPECS_FOUND_PROMPT and ADVANCED_SPECS_NOT_FOUND_PROMPT

# Vendor Matcher Tool prompts removed - tool replaced by deep_analysis_agent
# Deep analysis uses prompts from: prompts/deep_analysis/prompts.py

# Search Agent prompts (moved to search_agent module)

# Note: Schema Mapping Tool has been removed - schema mapping now done inline in validation_agent

__all__ = []
