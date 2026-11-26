"""
Agent Health Check Infrastructure
Provides base classes and utilities for checking agent health status

Resilience features added:
- check_llm_functional() result is cached for LLM_HEALTH_CACHE_TTL_SECONDS (default 60s)
  so the /health endpoint doesn't hammer the LLM API on every poll.
- check_llm_functional() uses a background thread with a hard timeout so a
  slow provider never blocks the health endpoint indefinitely.
"""

import concurrent.futures
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Literal

logger = logging.getLogger(__name__)

# ── LLM health-check result cache ───────────────────────────────────────────
# Stores the last DependencyStatus returned by check_llm_functional() along
# with the timestamp so repeated /health polls reuse the cached result.
_LLM_HEALTH_CACHE_TTL: int = int(os.getenv("LLM_HEALTH_CACHE_TTL_SECONDS", "60"))
_LLM_FUNCTIONAL_TIMEOUT: int = int(os.getenv("LLM_HEALTH_TIMEOUT_SECONDS", "10"))

_llm_health_cache: dict[str, tuple[float, "DependencyStatus"]] = {}
_llm_health_cache_lock = threading.Lock()

# ── MongoDB health-check result cache ───────────────────────────────────────
_MONGO_HEALTH_CACHE_TTL: int = 30  # 30 seconds ttl to prevent TooManyLogicalSessions
_mongo_health_cache: dict[str, tuple[float, "DependencyStatus"]] = {}
_mongo_health_cache_lock = threading.Lock()


@dataclass
class DependencyStatus:
    """Status of a single dependency"""
    name: str
    status: Literal["available", "unavailable", "untested"]
    error: str | None = None


@dataclass
class AgentMetrics:
    """Performance metrics for an agent"""
    request_count: int = 0
    total_response_time: float = 0.0
    error_count: int = 0
    total_tokens_used: int = 0

    @property
    def avg_response_time(self) -> float:
        """Calculate average response time"""
        return self.total_response_time / max(self.request_count, 1)

    @property
    def error_rate(self) -> float:
        """Calculate error rate (0.0 to 1.0)"""
        return self.error_count / max(self.request_count, 1)


@dataclass
class AgentHealthStatus:
    """Overall health status of an agent"""
    agent_name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    dependencies: dict[str, DependencyStatus]
    last_check: datetime
    metrics: AgentMetrics | None = None
    error_message: str | None = None


class AgentHealthChecker:
    """
    Base class for agent health checking
    Provides common dependency check methods
    """

    def check_llm_functional(self, provider: str = "deepinfra") -> "DependencyStatus":
        """
        Test LLM API with an actual call (FUNCTIONAL TEST).

        Results are cached for LLM_HEALTH_CACHE_TTL_SECONDS (default 60 s) so
        repeated /health polls do not hammer the LLM API.  The call itself is
        capped at LLM_HEALTH_TIMEOUT_SECONDS (default 10 s) so a slow provider
        never blocks the health endpoint.

        Args:
            provider: LLM provider name (google, openai, anthropic, etc.)

        Returns:
            DependencyStatus indicating if LLM is working functionally
        """
        cache_key = f"llm_functional_{provider}"

        # ── Return cached result if still fresh ─────────────────────────────
        with _llm_health_cache_lock:
            cached = _llm_health_cache.get(cache_key)
            if cached:
                ts, result = cached
                age = time.time() - ts
                if age < _LLM_HEALTH_CACHE_TTL:
                    logger.debug(
                        f"[AGENT_HEALTH] LLM health cache hit for {provider} "
                        f"(age {age:.0f}s / TTL {_LLM_HEALTH_CACHE_TTL}s)"
                    )
                    return result

        # ── Perform the actual test with a hard timeout ──────────────────────
        def _run_test() -> "DependencyStatus":
            from common.ai.llm import get_deterministic_flash
            llm = get_deterministic_flash()
            test_response = llm.invoke("Say 'OK'")
            if test_response and len(str(test_response).strip()) > 0:
                return DependencyStatus(
                    name=f"llm_{provider}_functional",
                    status="available"
                )
            return DependencyStatus(
                name=f"llm_{provider}_functional",
                status="unavailable",
                error="LLM returned empty response"
            )

        result: DependencyStatus
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_test)
                try:
                    result = future.result(timeout=_LLM_FUNCTIONAL_TIMEOUT)
                except concurrent.futures.TimeoutError:
                    logger.error(
                        f"[AGENT_HEALTH] LLM functional test timed out after "
                        f"{_LLM_FUNCTIONAL_TIMEOUT}s (provider={provider})"
                    )
                    result = DependencyStatus(
                        name=f"llm_{provider}_functional",
                        status="unavailable",
                        error=f"Functional test timed out after {_LLM_FUNCTIONAL_TIMEOUT}s"
                    )
        except Exception as e:
            logger.error(f"[AGENT_HEALTH] LLM functional test failed: {e}")
            result = DependencyStatus(
                name=f"llm_{provider}_functional",
                status="unavailable",
                error=f"Functional test failed: {e}"
            )

        # ── Cache and return ─────────────────────────────────────────────────
        with _llm_health_cache_lock:
            _llm_health_cache[cache_key] = (time.time(), result)

        return result

    def check_llm_connectivity(self, provider: str = "deepinfra") -> DependencyStatus:
        """
        Test LLM API key presence (not actual call to avoid rate limits)

        Args:
            provider: LLM provider name (deepinfra, etc.)

        Returns:
            DependencyStatus indicating if LLM is configured
        """
        try:
            # Map provider to environment variable names
            env_vars = {
                "deepinfra": ["DEEPINFRA_API_KEY"],
                "google": ["GOOGLE_API_KEY"],
                "openai": ["OPEN_API_KEY", "OPEN_API_KEY1"],
                "anthropic": ["ANTHROPIC_API_KEY"],
                "xai": ["XAI_API_KEY"],
            }

            provider_keys = env_vars.get(provider.lower(), ["DEEPINFRA_API_KEY"])

            # Check if any of the keys exist and are non-empty
            for key_name in provider_keys:
                api_key = os.getenv(key_name, "")
                if api_key and len(api_key) > 10:
                    return DependencyStatus(
                        name=f"llm_{provider}",
                        status="available"
                    )

            # No valid key found
            return DependencyStatus(
                name=f"llm_{provider}",
                status="unavailable",
                error=f"No valid API key found for {provider}"
            )

        except Exception as e:
            logger.error(f"[AGENT_HEALTH] LLM connectivity check failed: {str(e)}")
            return DependencyStatus(
                name=f"llm_{provider}",
                status="unavailable",
                error=str(e)
            )

    def check_mongodb_collection(self, collection_name: str) -> DependencyStatus:
        """
        Test MongoDB collection accessibility

        Results are cached for _MONGO_HEALTH_CACHE_TTL seconds to prevent
        'TooManyLogicalSessions' errors during concurrent /health polling.

        Args:
            collection_name: Name of the MongoDB collection to check

        Returns:
            DependencyStatus indicating if collection is accessible
        """
        cache_key = f"mongo_{collection_name}"

        # ── Return cached result if still fresh ─────────────────────────────
        with _mongo_health_cache_lock:
            cached = _mongo_health_cache.get(cache_key)
            if cached:
                ts, result = cached
                if time.time() - ts < _MONGO_HEALTH_CACHE_TTL:
                    return result

        try:
            from common.infra.mongodb_config import mongodb_manager

            # Test connection with ping
            mongodb_manager.client.admin.command('ping')

            # Test collection access
            collection = mongodb_manager.get_collection(collection_name)

            # Quick count to verify read access (limit to 1 for performance)
            collection.count_documents({}, limit=1)

            result = DependencyStatus(
                name=f"mongodb_{collection_name}",
                status="available"
            )

        except Exception as e:
            logger.error(f"[AGENT_HEALTH] MongoDB collection check failed for {collection_name}: {str(e)}")
            result = DependencyStatus(
                name=f"mongodb_{collection_name}",
                status="unavailable",
                error=str(e)
            )

        # ── Cache and return ─────────────────────────────────────────────────
        with _mongo_health_cache_lock:
            _mongo_health_cache[cache_key] = (time.time(), result)

        return result

    def check_prompt_file(self, prompt_path: str) -> DependencyStatus:
        """
        Test prompt file readability

        Args:
            prompt_path: Absolute or relative path to prompt file

        Returns:
            DependencyStatus indicating if prompt file is readable
        """
        try:
            with open(prompt_path, encoding='utf-8') as f:
                content = f.read()

                if len(content) < 10:
                    raise ValueError("Prompt file is too short (less than 10 characters)")

            file_name = os.path.basename(prompt_path)
            return DependencyStatus(
                name=f"prompt_{file_name}",
                status="available"
            )

        except Exception as e:
            logger.error(f"[AGENT_HEALTH] Prompt file check failed for {prompt_path}: {str(e)}")
            file_name = os.path.basename(prompt_path) if prompt_path else "unknown"
            return DependencyStatus(
                name=f"prompt_{file_name}",
                status="unavailable",
                error=str(e)
            )

    def check_agent_importable(self, module_path: str, function_name: str) -> DependencyStatus:
        """
        Test agent module importability

        Args:
            module_path: Python module path (e.g., "search.agents.validation_agent")
            function_name: Function name to check (e.g., "run_validation_agent")

        Returns:
            DependencyStatus indicating if agent is importable
        """
        try:
            # Import the module
            module = __import__(module_path, fromlist=[function_name])

            # Check if function exists
            if not hasattr(module, function_name):
                raise AttributeError(f"Function {function_name} not found in module {module_path}")

            return DependencyStatus(
                name=f"agent_{function_name}",
                status="available"
            )

        except Exception as e:
            logger.error(f"[AGENT_HEALTH] Agent import check failed for {module_path}.{function_name}: {str(e)}")
            return DependencyStatus(
                name=f"agent_{function_name}",
                status="unavailable",
                error=str(e)
            )


class AgentMetricsTracker:
    """
    Thread-safe metrics collection across all agents
    Singleton pattern - use global instance below
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._metrics = {}
                    cls._instance._metrics_lock = threading.Lock()
        return cls._instance

    def record_request(self, agent_name: str, response_time: float, tokens: int, success: bool):
        """
        Record request metrics for an agent

        Args:
            agent_name: Name of the agent (router_classifier, chat, search, solution)
            response_time: Time taken to process request in seconds
            tokens: Number of tokens used (LLM)
            success: Whether request succeeded or failed
        """
        with self._metrics_lock:
            if agent_name not in self._metrics:
                self._metrics[agent_name] = AgentMetrics()

            metrics = self._metrics[agent_name]
            metrics.request_count += 1
            metrics.total_response_time += response_time
            metrics.total_tokens_used += tokens

            if not success:
                metrics.error_count += 1

            logger.info(
                f"[AGENT_METRICS] {agent_name} - "
                f"Request #{metrics.request_count} | "
                f"Time: {response_time:.3f}s | "
                f"Tokens: {tokens} | "
                f"Success: {success}"
            )

    def get_metrics(self, agent_name: str) -> AgentMetrics:
        """
        Get current metrics for an agent

        Args:
            agent_name: Name of the agent

        Returns:
            AgentMetrics for the agent (or default if not tracked yet)
        """
        with self._metrics_lock:
            return self._metrics.get(agent_name, AgentMetrics())

    def reset_metrics(self, agent_name: str = None):
        """
        Reset metrics (for testing or on-demand)

        Args:
            agent_name: Specific agent to reset, or None to reset all
        """
        with self._metrics_lock:
            if agent_name:
                self._metrics[agent_name] = AgentMetrics()
                logger.info(f"[AGENT_METRICS] Reset metrics for {agent_name}")
            else:
                self._metrics.clear()
                logger.info("[AGENT_METRICS] Reset all agent metrics")


# Global singleton instance
agent_metrics_tracker = AgentMetricsTracker()


def track_agent_metrics(agent_name: str):
    """
    Decorator to automatically track agent request metrics

    Usage:
        @track_agent_metrics("chat")
        def query_chat(...):
            # agent code

    Args:
        agent_name: Name of the agent being tracked
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            tokens_used = 0

            try:
                result = func(*args, **kwargs)

                # Try to extract token usage from result if available
                if isinstance(result, dict):
                    # Check for token metadata
                    if 'metadata' in result and 'total_tokens' in result['metadata']:
                        tokens_used = result['metadata']['total_tokens']
                    elif 'tokens_used' in result:
                        tokens_used = result['tokens_used']

                return result

            except Exception as e:
                success = False
                logger.error(f"[AGENT_METRICS] {agent_name} failed: {str(e)}")
                raise

            finally:
                response_time = time.time() - start_time
                agent_metrics_tracker.record_request(
                    agent_name=agent_name,
                    response_time=response_time,
                    tokens=tokens_used,
                    success=success
                )

        return wrapper
    return decorator
