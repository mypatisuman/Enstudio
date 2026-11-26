
from common.ai.llm.manager import (
    get_flash_llm,
    get_pro_llm,
    get_lite_llm,
    get_flash_with_search,
    get_solution_pro_llm,
    get_solution_flash_llm,
    clear_llm_cache,
    with_json_mode,
    get_llm_for_task,
    get_deterministic_flash,
    get_creative_flash,
    get_deterministic_pro,
    get_creative_pro,
    get_default_llm,
    get_creative_llm,
    get_provider_info,
)
from common.ai.llm.tracking import log_model_usage, record_manual_usage
from common.ai.llm.config import (
    LLM_PROVIDER,
    SOLUTION_LLM_PROVIDER,
)

# Legacy constants expected by older code
GEMINI_PRO_MODEL = "gemini-2.5-pro"
GEMINI_FLASH_MODEL = "gemini-2.5-flash"
GEMINI_LITE_MODEL = "gemini-2.5-flash-lite"
