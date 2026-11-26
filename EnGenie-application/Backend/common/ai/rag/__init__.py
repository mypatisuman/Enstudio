"""
RAG (Retrieval-Augmented Generation) & Knowledge Modules

Consolidates knowledge and RAG implementations for the agentic backend:
- product_hierarchy_repository: 5-Tier hierarchy traversal for standard certifications & technical specs
- strategy_rag: RAG for vendor strategy documents
- chat_rag: Chat queries with MongoDB context
- taxonomy_rag: Category name to database name mapping + normalization + integration
- assets_rag: Assets extraction, asset configuration, and diagnostics (consolidated)
"""

__all__ = [
    # Diagnostics RAG
    "add_diagnostic_code",
    # Assets RAG
    "check_assets_rag_health",
    "check_diagnostics_rag_health",
    "delete_user_assets_data",
    "extract_assets_on_demand",
    "get_assets_collection",
    # Asset Config RAG
    "create_configuration",
    "create_diagnostic_session",
    "delete_configuration",
    "delete_user_diagnostic_data",
    "detect_config_gaps",
    "extract_config_from_text",
    "generate_yaml_for_config",
    "get_diagnostic_statistics",
    "ingest_instrument_logs",
    "list_configurations",
    "search_diagnostic_codes",
    "search_diagnostics_for_chat",
    "update_configuration",
    "update_diagnostic_session",
    # Chat RAG
    "clear_query_cache",
    "ensure_mongodb_indexes",
    "query_chat_rag",
    "search_vendors_chat",
    # Standard RAG
    "get_standards_collection",
    "get_standards_for_category",
]

# Import from standard_rag (UPDATED - removed embedding functions)
# Import from chat_rag
# Import from assets_rag (assets + asset_config + diagnostics)
from .assets_rag import (
    # Diagnostics RAG
    add_diagnostic_code,
    # Assets RAG
    check_assets_rag_health,
    check_diagnostics_rag_health,
    # Asset Config RAG
    create_configuration,
    create_diagnostic_session,
    delete_configuration,
    delete_user_assets_data,
    delete_user_diagnostic_data,
    detect_config_gaps,
    extract_assets_on_demand,
    extract_config_from_text,
    generate_yaml_for_config,
    get_assets_collection,
    get_diagnostic_statistics,
    ingest_instrument_logs,
    list_configurations,
    search_diagnostic_codes,
    search_diagnostics_for_chat,
    update_configuration,
    update_diagnostic_session,
)
from .chat_rag import (
    clear_query_cache,
    ensure_mongodb_indexes,
    query_chat_rag,
    search_vendors_chat,
)
def get_standards_collection():
    from common.infra.mongodb_config import Collections, get_mongodb_connection
    return get_mongodb_connection()[Collections.STANDARDS]

from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
get_standards_for_category = ProductHierarchyRepository.get_standards_for_category

# Import from strategy_rag
from .strategy_rag import (
    search_vendors_rag,
)

# Import from taxonomy_rag (consolidated single file)
from .taxonomy_rag import (
    SpecificationRetriever,
    # Classes
    TaxonomyContextManager,
    TaxonomyIntegrationAdapter,
    TaxonomyNormalizationAgent,
    TaxonomyRAG,
    generate_short_description,
    # Lightweight live matcher (used by deep_instrument_analysis_agent, validation_agent)
    get_taxonomy_for_category,
    # Helpers
    get_taxonomy_rag,
    prepare_batch_search_payload,
    # Integration pipeline wrappers
    prepare_for_search_workflow,
    prepare_search_payload_for_item,
)

__all__ = [
    # Asset Configuration RAG
    "extract_config_from_text",
    "generate_yaml_for_config",
    "detect_config_gaps",
    "list_configurations",
    "create_configuration",
    "update_configuration",
    "delete_configuration",
    # Standard RAG
    "get_standards_for_category",
    "get_standards_collection",
    # Strategy RAG
    "search_vendors_rag",
    # Chat RAG
    "query_chat_rag",
    "search_vendors_chat",
    "clear_query_cache",
    "ensure_mongodb_indexes",
    # Taxonomy RAG — functions
    "get_taxonomy_for_category",
    "get_taxonomy_rag",
    "generate_short_description",
    "prepare_for_search_workflow",
    "prepare_search_payload_for_item",
    "prepare_batch_search_payload",
    # Taxonomy RAG — classes
    "TaxonomyContextManager",
    "TaxonomyRAG",
    "SpecificationRetriever",
    "TaxonomyNormalizationAgent",
    "TaxonomyIntegrationAdapter",
    # Diagnostics RAG — functions
    "ingest_instrument_logs",
    "add_diagnostic_code",
    "search_diagnostic_codes",
    "create_diagnostic_session",
    "update_diagnostic_session",
    "search_diagnostics_for_chat",
    "get_diagnostic_statistics",
    "delete_user_diagnostic_data",
    "check_diagnostics_rag_health",
]

