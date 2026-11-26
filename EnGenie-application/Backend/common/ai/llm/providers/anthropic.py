
import logging
from common.ai.llm.config import ANTHROPIC_API_KEY, _ANTHROPIC_MAX_TOKENS

logger = logging.getLogger(__name__)

def create_anthropic_llm(model_name: str, tier: str, temperature: float, search_enabled: bool, token_callback):
    from langchain_anthropic import ChatAnthropic
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set in environment.")
    if search_enabled:
        logger.warning("Web search is a Google-specific feature. Returning standard Anthropic model.")

    return ChatAnthropic(
        model=model_name,
        api_key=ANTHROPIC_API_KEY,
        temperature=temperature,
        max_tokens=_ANTHROPIC_MAX_TOKENS.get(tier, 16384),
        timeout=600,
        callbacks=[token_callback],
    )
