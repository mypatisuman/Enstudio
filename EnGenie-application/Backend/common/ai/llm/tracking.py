
import logging
import threading
import time
from langchain_core.callbacks import BaseCallbackHandler
from common.ai.llm.config import MODEL_COSTS

logger = logging.getLogger(__name__)

class TokenUsageCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that automatically logs token usage
    after every LLM call. Works with all providers (Google, OpenAI, Anthropic).
    """
    def __init__(self, model_name: str, provider: str, user_id: str | None = None, agent_type: str | None = None, feature_type: str | None = None, request_type: str | None = None, session_id: str | None = None):
        super().__init__()
        self.model_name = model_name
        self.provider = provider
        self.user_id = user_id
        self.agent_type = agent_type
        self.feature_type = feature_type
        self.request_type = request_type
        self.session_id = session_id
        self._local = threading.local()

    @property
    def start_time(self) -> float:
        return getattr(self._local, 'start_time', 0.0)

    @start_time.setter
    def start_time(self, value: float) -> None:
        self._local.start_time = value

    def on_llm_start(self, _serialized, _prompts, **kwargs):
        self.start_time = time.time()
        metadata = kwargs.get('metadata') or {}
        if 'user_id' in metadata: self._local.user_id = metadata['user_id']
        if 'agent_type' in metadata: self._local.agent_type = metadata['agent_type']

    def on_chat_model_start(self, _serialized, _messages, **kwargs):
        self.start_time = time.time()
        metadata = kwargs.get('metadata') or {}
        if 'user_id' in metadata: self._local.user_id = metadata['user_id']
        if 'agent_type' in metadata: self._local.agent_type = metadata['agent_type']

    def on_llm_end(self, response, **kwargs):
        elapsed = time.time() - self.start_time if self.start_time else 0
        input_tokens = output_tokens = total_tokens = 0

        try:
            if hasattr(response, 'llm_output') and response.llm_output:
                token_usage = response.llm_output.get('token_usage', {}) or response.llm_output.get('usage', {})
                input_tokens = token_usage.get('prompt_tokens', 0) or token_usage.get('input_tokens', 0) or 0
                output_tokens = token_usage.get('completion_tokens', 0) or token_usage.get('output_tokens', 0) or 0
                total_tokens = token_usage.get('total_tokens', 0) or (input_tokens + output_tokens)

            if not total_tokens and hasattr(response, 'generations'):
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, 'message') and hasattr(gen.message, 'usage_metadata') and gen.message.usage_metadata:
                            msg_usage = gen.message.usage_metadata
                            if isinstance(msg_usage, dict):
                                input_tokens = msg_usage.get('input_tokens', 0) or input_tokens
                                output_tokens = msg_usage.get('output_tokens', 0) or output_tokens
                                total_tokens = msg_usage.get('total_tokens', 0) or total_tokens
                        if hasattr(gen, 'generation_info') and gen.generation_info:
                            usage = gen.generation_info.get('usage_metadata', {}) or gen.generation_info.get('usage', {})
                            input_tokens = usage.get('prompt_token_count', 0) or usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0) or input_tokens
                            output_tokens = usage.get('candidates_token_count', 0) or usage.get('completion_tokens', 0) or usage.get('output_tokens', 0) or output_tokens
                            total_tokens = usage.get('total_token_count', 0) or usage.get('total_tokens', 0) or (input_tokens + output_tokens)
        except Exception as e:
            logger.debug(f"[TOKEN_USAGE] Could not extract token counts: {e}")

        total_cost = 0.0
        cost_str = ""
        if total_tokens > 0:
            from common.ai.llm.config import _lookup_model_cost
            costs = _lookup_model_cost(self.model_name)
            if costs:
                input_cost = (input_tokens / 1_000_000) * costs["input"]
                output_cost = (output_tokens / 1_000_000) * costs["output"]
                total_cost = input_cost + output_cost
                cost_str = f" | Est.Cost: ${total_cost:.6f}"

        logger.info(
            f"[TOKEN_USAGE] Provider: {self.provider} | Model: {self.model_name} | "
            f"Input: {input_tokens:,} tokens | Output: {output_tokens:,} tokens | "
            f"Total: {total_tokens:,} tokens | Time: {elapsed:.2f}s{cost_str}"
        )

        if total_tokens > 0:
            # 1) Always record production usage (when we have a user). Unaffected
            #    by benchmark mode so dashboards/billing stay complete.
            try:
                user_id = getattr(self._local, 'user_id', None) or self.user_id
                if user_id:
                    agent_type = getattr(self._local, 'agent_type', None) or self.agent_type
                    from common.monitoring.usage import llm_usage_tracker
                    llm_usage_tracker.record_usage(
                        user_id=str(user_id), provider=self.provider, model_name=self.model_name,
                        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
                        estimated_cost=total_cost, response_time_ms=elapsed * 1000, agent_type=agent_type, feature_type=self.feature_type, request_type=self.request_type, session_id=self.session_id
                    )
            except Exception as e: logger.warning(f"[TOKEN_USAGE] Failed to store usage in MongoDB: {e}")

            # 2) Additionally, when inside a benchmark context (suite or live run),
            #    attribute this call to that run/test as well.
            try:
                from common.monitoring.benchmarking.context import get_benchmark_context
                bench_ctx = get_benchmark_context()
            except Exception:
                bench_ctx = None

            if bench_ctx:
                try:
                    from common.monitoring.usage.benchmark_usage_tracker import benchmark_usage_tracker
                    benchmark_usage_tracker.record_benchmark_usage(
                        run_id=bench_ctx['run_id'], test_id=bench_ctx['test_id'], provider=self.provider,
                        model_name=self.model_name, input_tokens=input_tokens, output_tokens=output_tokens,
                        total_tokens=total_tokens, estimated_cost=total_cost, response_time_ms=elapsed * 1000,
                        agent_type=self.agent_type, feature_type=self.feature_type, request_type=self.request_type
                    )
                except Exception as e: logger.warning(f"[TOKEN_USAGE] Failed to store benchmark usage: {e}")

    def on_llm_error(self, error, **kwargs):
        elapsed = time.time() - self.start_time if self.start_time else 0
        error_str = str(error).lower()
        _RATE_LIMIT_SIGNALS = ('429', 'rate limit', 'quota exceeded', 'resource_exhausted', 'too many requests', 'ratequotaexceeded', 'quota_exceeded')
        is_rate_limit = any(sig in error_str for sig in _RATE_LIMIT_SIGNALS)

        if is_rate_limit and self.provider == 'google':
            logger.warning(f"[LLM_MANAGER] Rate limit / quota error detected for Google (model={self.model_name}) — triggering key rotation")
            from common.ai.llm.providers.google import rotate_google_key
            rotate_google_key()

        logger.error(f"[TOKEN_USAGE] Provider: {self.provider} | Model: {self.model_name} | ERROR after {elapsed:.2f}s: {error}")

def log_model_usage(model_name: str, input_tokens: int, output_tokens: int):
    if model_name not in MODEL_COSTS: return
    costs = MODEL_COSTS[model_name]
    total_cost = ((input_tokens / 1_000_000) * costs["input"]) + ((output_tokens / 1_000_000) * costs["output"])
    logger.info(f"[TOKEN_USAGE] Provider: {costs.get('provider', 'unknown')} | Model: {model_name} | Input: {input_tokens:,} tokens | Output: {output_tokens:,} tokens | Est. Cost: ${total_cost:.6f}")

def record_manual_usage(model_name: str, input_tokens: int, output_tokens: int, user_id: str | None = None, elapsed_time: float = 0.0, agent_type: str | None = None, feature_type: str | None = None, request_type: str | None = None, session_id: str | None = None):
    if model_name not in MODEL_COSTS: return
    costs = MODEL_COSTS[model_name]
    provider = costs.get('provider', 'unknown')
    total_cost = ((input_tokens / 1_000_000) * costs["input"]) + ((output_tokens / 1_000_000) * costs["output"])
    logger.info(f"[TOKEN_USAGE][MANUAL] Provider: {provider} | Model: {model_name} | Input: {input_tokens:,} tokens | Output: {output_tokens:,} tokens | Est. Cost: ${total_cost:.6f}")
    if user_id:
        try:
            from common.monitoring.usage import llm_usage_tracker
            llm_usage_tracker.record_usage(
                user_id=str(user_id), provider=provider, model_name=model_name, input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens+output_tokens,
                estimated_cost=total_cost, response_time_ms=elapsed_time * 1000, agent_type=agent_type, feature_type=feature_type, request_type=request_type, session_id=session_id
            )
        except Exception as e: logger.warning(f"[TOKEN_USAGE] Failed to store manual usage in MongoDB: {e}")
