
"""
LLM Configuration & Constants
"""
import os

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepinfra").lower().strip()
FALLBACK_LLM_PROVIDER = os.getenv("FALLBACK_LLM_PROVIDER", "").lower().strip()
FALLBACK_LLM_PROVIDER2 = os.getenv("FALLBACK_LLM_PROVIDER2", "").lower().strip()
SOLUTION_LLM_PROVIDER = os.getenv("SOLUTION_LLM_PROVIDER", LLM_PROVIDER).lower().strip()

# --- Disabled Providers (DeepInfra only active) ---
# GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# GOOGLE_API_KEY1 = os.getenv("GOOGLE_API_KEY1")
# OPEN_API_KEY   = os.getenv("OPEN_API_KEY")
# OPEN_API_KEY1 = os.getenv("OPEN_API_KEY1")
# AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
# AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
# AZURE_OPENAI_DEPLOYMENTS = {
#     "pro":   os.getenv("AZURE_OPENAI_DEPLOYMENT_PRO",   "gpt-5.4"),
#     "flash": os.getenv("AZURE_OPENAI_DEPLOYMENT_FLASH", "gpt-5.4-mini"),
#     "lite":  os.getenv("AZURE_OPENAI_DEPLOYMENT_NANO",  "gpt-5.4-nano"),
# }
# ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# XAI_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")

KEY_ROTATION_BACKOFF_SECS = float(os.getenv("KEY_ROTATION_BACKOFF_SECS", "1.5"))

PROVIDER_MODELS = {
    # "google": {
    #     "pro": "gemini-2.5-pro",
    #     "flash": "gemini-2.5-flash",
    #     "lite": "gemini-2.5-flash-lite",
    # },
    # "openai": {
    #     "pro": "gpt-5.4",
    #     "flash": "gpt-5.4-mini",
    #     "lite": "gpt-5.4-nano",
    # },
    # "anthropic": {
    #     "pro": "claude-sonnet-4-5-20250929",
    #     "flash": "claude-haiku-4-5-20251001",
    #     "lite": "claude-haiku-4-5-20251001",
    # },
    # "grok": {
    #     "pro": "grok-2-latest",
    #     "flash": "grok-2-mini",
    #     "lite": "grok-2-mini",
    # },
    # "kimi": {
    #     "pro": "Kimi-K2.6",
    #     "flash": "Kimi-K2.5",
    #     "lite": "Kimi-K2.5",
    # },
    # "replicate": {
    #     "pro": os.getenv("REPLICATE_MODEL_PRO", "google-deepmind/gemma-3-27b-it"),
    #     "flash": os.getenv("REPLICATE_MODEL_FLASH", "google-deepmind/gemma-3-27b-it"),
    #     "lite": os.getenv("REPLICATE_MODEL_LITE", "google-deepmind/gemma-3-27b-it"),
    # },
    # DeepInfra: OpenAI-compatible serving of open models
    "deepinfra": {
        "pro": os.getenv("DEEPINFRA_MODEL_PRO", "Qwen/Qwen3-VL-30B-A3B-Instruct"),
        "flash": os.getenv("DEEPINFRA_MODEL_FLASH", "Qwen/Qwen3-VL-30B-A3B-Instruct"),
        "lite": os.getenv("DEEPINFRA_MODEL_LITE", "Qwen/Qwen3-VL-30B-A3B-Instruct"),
    },
}

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


MODEL_COSTS = {
    # DeepInfra Vision & Multimodal models list prices (deepinfra.com)
    "Qwen/Qwen3-VL-30B-A3B-Instruct": {"input": 0.15, "output": 0.35, "tier": "complex", "provider": "deepinfra"},
    "Qwen/Qwen3-VL-235B-A22B-Instruct": {"input": 0.35, "output": 0.70, "tier": "complex", "provider": "deepinfra"},
    # DeepInfra Gemma models list prices (deepinfra.com)
    "google/gemma-4-31B-it": {"input": 0.13, "output": 0.38, "tier": "complex", "provider": "deepinfra"},
    "google/gemma-4-31B-it-turbo": {"input": 0.09, "output": 0.34, "tier": "complex", "provider": "deepinfra"},
}


def _lookup_model_cost(model_name: str) -> dict | None:
    """Case-insensitive MODEL_COSTS lookup. Returns None when unknown."""
    if not model_name:
        return None
    if model_name in MODEL_COSTS:
        return MODEL_COSTS[model_name]
    lc = model_name.lower()
    for k, v in MODEL_COSTS.items():
        if k.lower() == lc:
            return v
    return None

TEMP_DETERMINISTIC = 0.1
TEMP_CREATIVE = 0.7
TEMP_BALANCED = 0.3

# Bypass the manager's built-in Kimi pro->flash downgrade. Default off (preserves
# the production safety workaround for Kimi's reasoning-token bug).
# (Note: This environment setting is retained as a legacy flag for provider-level downgrades).
DISABLE_KIMI_PRO_DOWNGRADE = os.getenv(
    "DISABLE_KIMI_PRO_DOWNGRADE", "false"
).lower().strip() in {"1", "true", "yes", "on"}
