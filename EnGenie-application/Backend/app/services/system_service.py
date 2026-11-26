import os
import psutil
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import text

# Health cache for SQL
_sql_health_cache = {
    "status": "unknown",
    "expires_at": 0,
    "error": None
}
_SQL_HEALTH_CACHE_TTL = 30

def check_database():
    """Check all database connections in parallel"""
    from app.models.db.base import db
    components = {}

    # SQL Database - with caching to avoid pool exhaustion
    now = time.time()
    if (
        _sql_health_cache["status"] == "connected"
        and now < _sql_health_cache["expires_at"]
    ):
        components["sql_database"] = {"status": "connected", "type": "MySQL/PostgreSQL", "cached": True}
    else:
        try:
            db.session.execute(text('SELECT 1'))
            db.session.rollback()  # Release connection immediately
            components["sql_database"] = {"status": "connected", "type": "MySQL/PostgreSQL"}
            _sql_health_cache["status"] = "connected"
            _sql_health_cache["expires_at"] = now + _SQL_HEALTH_CACHE_TTL
            _sql_health_cache["error"] = None
        except Exception as e:
            logging.error(f"[HEALTH CHECK] SQL Database disconnected or error: {str(e)}")
            components["sql_database"] = {"status": "disconnected", "error": str(e)[:200]}
            _sql_health_cache["status"] = "disconnected"
            _sql_health_cache["expires_at"] = now + 60
            _sql_health_cache["error"] = str(e)[:200]

    # MongoDB
    try:
        from common.infra.mongodb_config import mongodb_manager
        mongodb_manager.client.admin.command('ping')
        collection_count = len(mongodb_manager.database.list_collection_names())
        components["mongodb"] = {
            "status": "connected",
            "database": mongodb_manager.database.name,
            "collections": collection_count
        }
    except Exception as e:
        logging.error(f"[HEALTH CHECK] MongoDB disconnected or error: {str(e)}")
        components["mongodb"] = {"status": "disconnected", "error": str(e)}

    # Redis
    try:
        from common.infra.database import redis_client
        if redis_client:
            redis_client.ping()
            info = redis_client.info('server')
            components["redis"] = {
                "status": "connected",
                "version": info.get('redis_version', 'unknown')
            }
        else:
            components["redis"] = {"status": "not_configured"}
    except Exception as e:
        components["redis"] = {"status": "disconnected", "error": str(e)}

    # Azure Blob Storage
    try:
        from common.infra.azure_blob import azure_blob_manager
        blob_test = azure_blob_manager.test_connection()
        if blob_test.get("connected"):
            components["azure_blob"] = {
                "status": "connected",
                "account_name": blob_test.get("account_name"),
                "containers": len(blob_test.get("containers", []))
            }
        else:
            components["azure_blob"] = {
                "status": "disconnected" if blob_test.get("error") else "not_configured",
                "error": blob_test.get("error")
            }
    except Exception as e:
        components["azure_blob"] = {"status": "disconnected", "error": str(e)}

    return components

def check_chat_agent():
    """Check chat agent health - checks connectivity only"""
    try:
        from common.monitoring.health import AgentHealthChecker
        checker = AgentHealthChecker()
        llm_status = checker.check_llm_connectivity("google")
        return {
            "status": "healthy" if llm_status.status == "available" else "unhealthy",
            "llm": llm_status.status,
            "test_type": "connectivity"
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

def check_search_agent():
    """Check search agent + all 4 agents health"""
    try:
        from domain.search.agents.advanced_specs_agent import check_advanced_specs_agent_health
        from domain.search.agents.vendor_analysis_agent import check_vendor_analysis_agent_health
        from domain.search.agents.summary_agent import check_summary_agent_health
        from domain.search.agents.validation_agent import check_validation_agent_health

        validation_health = check_validation_agent_health()
        vendor_analysis_health = check_vendor_analysis_agent_health()
        summary_health = check_summary_agent_health()
        advanced_specs_health = check_advanced_specs_agent_health()

        all_statuses = [
            validation_health.status,
            vendor_analysis_health.status,
            summary_health.status,
            advanced_specs_health.status
        ]

        if all(s == "healthy" for s in all_statuses):
            overall_status = "healthy"
        elif any(s == "unhealthy" for s in all_statuses):
            overall_status = "unhealthy"
        else:
            overall_status = "degraded"

        return {
            "status": overall_status,
            "agents": {
                "validation": validation_health.status,
                "vendor_analysis": vendor_analysis_health.status,
                "summary": summary_health.status,
                "advanced_specs": advanced_specs_health.status
            }
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

def check_solution_agent():
    """Check solution agent health"""
    try:
        from domain.solution.workflows.solution_workflow import check_solution_agent_health
        solution_health = check_solution_agent_health()
        return {
            "status": solution_health.status,
            "agent": {
                "solution_agent": solution_health.status
            }
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

def check_system_resources():
    """Check system resources CPU/Mem/Disk"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return {
            "status": "healthy",
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "disk_percent": disk.percent
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

def check_api_keys():
    """Check that required API keys are configured (no network call)."""
    required_keys = ["GOOGLE_API_KEY", "GOOGLE_API_KEY1", "SERPER_API_KEY", "SERPAPI_KEY"]
    missing = [k for k in required_keys if not os.getenv(k)]
    if missing:
        return {"status": "unhealthy", "missing_keys": missing}
    return {"status": "healthy"}

def check_embedding_service():
    """Check embedding service availability."""
    try:
        from common.ai.embedding_manager import get_embedding_model
        return {"status": "available", **get_embedding_model()}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:100]}

def execute_deep_health_check() -> dict:
    """Execute all parallel deep health checks."""
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(check_database): "database",
            executor.submit(check_chat_agent): "chat_agent",
            executor.submit(check_search_agent): "search_agent",
            executor.submit(check_solution_agent): "solution_agent",
            executor.submit(check_system_resources): "system_resources",
            executor.submit(check_api_keys): "api_keys",
            executor.submit(check_embedding_service): "embedding_service"
        }

        components = {}
        for future in as_completed(futures):
            component_name = futures[future]
            try:
                components[component_name] = future.result()
            except Exception as e:
                components[component_name] = {"status": "unhealthy", "error": str(e)}

    return components
