"""
MongoDB Configuration and Connection Management
Handles MongoDB connection, GridFS setup, and database operations
"""

import logging
import os
import threading
from typing import Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

# Load environment variables
# load_dotenv()

logger = logging.getLogger(__name__)

# TTL for conversation_memory docs not linked to a saved project (see Collections.CONVERSATION_MEMORY)
_CONVERSATION_MEMORY_TTL_SECONDS = int(os.environ.get("CONVERSATION_MEMORY_TTL_DAYS", "30")) * 86400

# P2.8 FIX: Thread-safe singleton lock
_mongodb_singleton_lock = threading.Lock()


class MongoDBManager:
    """Singleton MongoDB connection manager with GridFS support"""

    _instance: Optional['MongoDBManager'] = None
    _client: MongoClient | None = None
    _database: Database | None = None
    # Separate client for the Restructured hierarchy DB when it lives on a
    # different cluster (RESTRUCTURED_DB_URI env var).  Falls back to the
    # main client when the env var is absent so single-cluster deployments
    # continue to work without any config change.
    _restructured_client: MongoClient | None = None

    def __new__(cls) -> 'MongoDBManager':
        # P2.8 FIX: Thread-safe singleton pattern
        if cls._instance is None:
            with _mongodb_singleton_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            # P0.x: Removed immediate _setup_connection call to ensure lazy init
            # after worker forks.

    def _setup_connection(self):
        """Setup MongoDB connection and GridFS"""
        if self._client is not None:
            return

        try:
            # Database name
            db_name = os.getenv('MONGODB_DATABASE', 'product-recommender')

            # Try service principal authentication first (for Azure Cosmos DB MongoDB vCore)
            azure_tenant_id = os.getenv('AZURE_TENANT_ID')
            azure_client_id = os.getenv('AZURE_CLIENT_ID')
            cosmos_endpoint = os.getenv('AZURE_COSMOS_ENDPOINT')  # e.g., "myaccount.mongo.cosmos.azure.com"

            if azure_tenant_id and azure_client_id and cosmos_endpoint:
                try:
                    from azure.identity import DefaultAzureCredential
                    from pymongo.auth_oidc import OIDCCallback, OIDCCallbackContext, OIDCCallbackResult

                    # OIDC callback for Azure AD token
                    class AzureIdentityTokenCallback(OIDCCallback):
                        def __init__(self, credential):
                            self.credential = credential

                        def fetch(self, context: OIDCCallbackContext) -> OIDCCallbackResult:
                            # Get token with correct scope for Azure Cosmos DB MongoDB vCore
                            token = self.credential.get_token(
                                "https://ossrdbms-aad.database.windows.net/.default"
                            )
                            return OIDCCallbackResult(access_token=token.token)

                    # Create Azure AD credential
                    credential = DefaultAzureCredential()
                    auth_properties = {"OIDC_CALLBACK": AzureIdentityTokenCallback(credential)}

                    # Build connection URI using mongodb+srv protocol (OIDC authentication)
                    # Note: No username/password in URI - authentication handled by OIDC callback
                    mongodb_uri = f"mongodb+srv://{cosmos_endpoint}/"

                    # Create MongoDB client with OIDC authentication
                    # P0.5 FIX: Added serverSelectionTimeoutMS and socketTimeoutMS to prevent
                    # worker threads from hanging indefinitely on unresponsive MongoDB
                    # P0.x FIX: Added connect=False for safer gevent/fork compatibility
                    self._client = MongoClient(
                        mongodb_uri,
                        connect=False,
                        connectTimeoutMS=120000,
                        serverSelectionTimeoutMS=30000,  # P0.5: 30s to pick a server
                        socketTimeoutMS=120000,          # P0.5: 120s individual read/write deadline
                        tls=True,
                        retryWrites=False,
                        authMechanism="MONGODB-OIDC",
                        authMechanismProperties=auth_properties,
                        maxIdleTimeMS=120000,
                        maxPoolSize=5,
                        minPoolSize=1,
                    )
                    self._database = self._client[db_name]

                    # Test connection
                    self._client.admin.command('ping')
                    logger.info(f"✅ Successfully connected to Azure Cosmos DB using service principal (OIDC): {db_name}")

                except ImportError as e:
                    logger.warning(f"[MONGODB] Required packages not installed: {e}. Falling back to connection string.")
                    logger.warning("[MONGODB] Ensure pymongo>=4.6.0 and azure-identity>=1.19.0 are installed")
                    self._client = None
                except Exception as e:
                    logger.warning(f"[MONGODB] Service principal auth failed, falling back to connection string: {e}")
                    self._client = None

            # Fallback to connection string authentication (current method)
            if self._client is None:
                mongodb_uri = os.getenv('MONGODB_URI')

                if not mongodb_uri:
                    logger.error("[MONGODB] No MongoDB credentials found - neither service principal nor connection string")
                    raise ValueError("MongoDB credentials not configured")

                # Create MongoDB client with connection string
                # P0.11 FIX: Added retryWrites=False for CosmosDB compatibility
                # P0.x FIX: Added connect=False for safer gevent/fork compatibility
                self._client = MongoClient(
                    mongodb_uri,
                    connect=False,
                    maxPoolSize=5,
                    minPoolSize=1,
                    maxIdleTimeMS=120000,
                    retryWrites=False,  # P0.11: CosmosDB doesn't support retryable writes
                    # Safety-net timeouts — generous enough to never affect normal operations.
                    # These only fire if the server is truly unresponsive / hung.
                    socketTimeoutMS=120000,          # 120s  — individual read/write deadline
                    serverSelectionTimeoutMS=30000,  # 30s   — pick a server from topology
                    connectTimeoutMS=30000,          # 30s   — establish the TCP connection
                )
                self._database = self._client[db_name]

                # Test connection
                self._client.admin.command('ping')
                logger.info(f"✅ Successfully connected to MongoDB using connection string: {db_name}")

        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    @property
    def client(self) -> MongoClient:
        """Get MongoDB client"""
        if self._client is None:
            self._setup_connection()
        return self._client

    @property
    def database(self) -> Database:
        """Get MongoDB database"""
        if self._database is None:
            self._setup_connection()
        return self._database

    def get_collection(self, name: str) -> Collection:
        """Get a specific collection"""
        return self.database[name]

    @property
    def restructured_client(self) -> MongoClient:
        """Return a MongoClient for the Restructured hierarchy DB.

        When RESTRUCTURED_DB_URI is set (pointing to a separate cluster that
        holds the enriched L0/L1/L2 views), a dedicated client is created and
        cached here.  Otherwise the main client is returned so single-cluster
        setups continue to work unchanged.
        """
        restructured_uri = os.getenv("RESTRUCTURED_DB_URI")
        if not restructured_uri:
            return self.client  # same cluster — use main connection

        if self._restructured_client is None:
            with _mongodb_singleton_lock:
                if self._restructured_client is None:
                    try:
                        self._restructured_client = MongoClient(
                            restructured_uri,
                            connect=False,
                            maxPoolSize=5,
                            minPoolSize=1,
                            maxIdleTimeMS=120000,
                            retryWrites=False,
                            socketTimeoutMS=120000,
                            serverSelectionTimeoutMS=30000,
                            connectTimeoutMS=30000,
                        )
                        self._restructured_client.admin.command("ping")
                        logger.info("✅ Connected to Restructured DB cluster via RESTRUCTURED_DB_URI")
                    except Exception as exc:
                        logger.error(f"[MONGODB] Restructured DB connection failed: {exc}; falling back to main client")
                        self._restructured_client = self.client
        return self._restructured_client

    def close(self):
        """Close MongoDB connection"""
        if self._client:
            self._client.close()
            self._client = None
            self._database = None
            logger.info("MongoDB connection closed")
        if self._restructured_client and self._restructured_client is not self._client:
            self._restructured_client.close()
            self._restructured_client = None

# Global instance
mongodb_manager = MongoDBManager()

# =========================================================================
# === QUERY PERFORMANCE TRACKING LISTENER ===
# =========================================================================
# We use PyMongo's CommandListener to intercept queries as they occur
# and feed them to the QueryPerformanceTracker.
import time as _time

from pymongo import monitoring


class QueryPerformanceListener(monitoring.CommandListener):
    def __init__(self):
        self.commands = {}
        self.ignored_collections = {
            'query_performance', 'endpoint_statistics', 'session_analytics',
            'storage_metrics', 'system.indexes'
        }

    def started(self, event):
        # We only track commands that likely scan/read/write data
        if event.command_name in ('find', 'aggregate', 'update', 'insert', 'delete', 'count'):
            collection_name = event.command.get(event.command_name)
            if isinstance(collection_name, str) and collection_name not in self.ignored_collections:
                self.commands[event.request_id] = (_time.time(), collection_name)

    def succeeded(self, event):
        command_info = self.commands.pop(event.request_id, None)
        if command_info is None:
            return

        start_time, collection_name = command_info
        execution_time_ms = (_time.time() - start_time) * 1000.0

        # Fast path: only forward to tracker if > 1000ms threshold
        # (reduces overhead of importing and processing fast queries)
        if execution_time_ms < 1000.0:
            return

        try:
            # Avoid circular import
            from common.monitoring.usage import query_performance_tracker
            query_performance_tracker.record_query(
                collection_name=collection_name,
                operation=event.command_name,
                execution_time_ms=execution_time_ms,
                query_filter=None,  # We don't get the query here safely without memory overhead
                result_count=len(event.reply.get('cursor', {}).get('firstBatch', [])) if 'cursor' in event.reply else None,
                is_indexed=None
            )
        except Exception:
            # Don't let tracking failure crash the application
            pass

    def failed(self, event):
        self.commands.pop(event.request_id, None)

# Register listener globally
try:
    monitoring.register(QueryPerformanceListener())
except Exception as e:
    logger.debug(f"[TRACKING] Failed to register query performance listener: {e}")
# =========================================================================

# Collection names constants
class Collections:
    """MongoDB collection names"""
    # Main collections
    SPECS = "specs"                          # Product type schemas
    VENDORS = "vendors"                      # Vendor product data
    ADVANCED_SPECIFICATIONS = "advanced_specifications"  # Cached advanced specifications
    IMAGES = "images"                        # Cached product images
    GENERIC_IMAGES = "generic_images"        # Cached generic product type images
    VENDOR_LOGOS = "vendor_logos"            # Cached vendor logos

    # User project management
    USER_PROJECTS = "user_projects"          # User saved projects

    # Strategy collection
    STRATERGY = "stratergy"                  # Strategy upload headers (blob links + metadata)

    # Standards collection
    STANDARDS = "standards"                  # Engineering standards data

    # Assets collection
    ASSETS = "assets"                        # Assert documents and data

    # Logging and Feedback collections
    LOGS = "logs"                            # User interaction logs (grouped by session)
    FEEDBACK = "feedback"                    # User feedback on recommendations

    # Asset Configuration collection
    ASSET_CONFIGURATIONS = "asset_configurations"  # Saved asset configuration documents + YAML

    # Instrument Diagnostics collections
    INSTRUMENT_LOGS = "instrument_logs"      # Time-series instrument readings & events
    DIAGNOSTIC_CODES = "diagnostic_codes"    # Known failure codes & troubleshooting guides
    DIAGNOSTIC_SESSIONS = "diagnostic_sessions"  # Analysis results per diagnostic session
    MONITOR_SOURCES = "monitor_sources"      # Configured external log source paths

    # Procurement collection
    PROCUREMENT_DEVICES = "procurement_devices"  # Equipment procurement registry
    USER_HYBRID_MEMORIES = "user_hybrid_memories" # Dynamic user interests and specifications profile

    # Search agent session context (structured schema/spec SSOT)
    SEARCH_SESSION_CONTEXT = "search_session_context"

    # Holistic gate session context (L2 store backing common/ai/memory/holistic.py)
    HOLISTIC_CONTEXT = "holistic_context"

    # Full conversation/chat turn history (L2 store backing common/ai/memory/core.py)
    CONVERSATION_MEMORY = "conversation_memory"

    # Embedded conversation episodes (user-level episodic memory backing common/ai/memory/episodes.py)
    CONVERSATION_EPISODES = "conversation_episodes"

    # The current P&ID drawing per user + solution session, with its revision,
    # pending engineer action and revision history (pid_graph_repository.py)
    PID_GRAPHS = "pid_graphs"

    # Product types searched by users but missing from the DB (auto-indexing audit queue)
    MISSING_PRODUCT_TYPES = "missing_product_types"

    # Credits system (per-user balance, append-only ledger, per-run charge records)
    USER_CREDITS = "user_credits"
    CREDIT_TRANSACTIONS = "credit_transactions"
    CREDIT_WORKFLOW_RUNS = "credit_workflow_runs"

def get_mongodb_connection():
    """Get MongoDB connection components"""
    return {
        'client': mongodb_manager.client,
        'database': mongodb_manager.database,
        'collections': {
            # Main collections
            'specs': mongodb_manager.get_collection(Collections.SPECS),
            'vendors': mongodb_manager.get_collection(Collections.VENDORS),
            'advanced_specifications': mongodb_manager.get_collection(Collections.ADVANCED_SPECIFICATIONS),
            'images': mongodb_manager.get_collection(Collections.IMAGES),
            'generic_images': mongodb_manager.get_collection(Collections.GENERIC_IMAGES),
            'vendor_logos': mongodb_manager.get_collection(Collections.VENDOR_LOGOS),

            # User project management
            'user_projects': mongodb_manager.get_collection(Collections.USER_PROJECTS),

            # Strategy collection
            'stratergy': mongodb_manager.get_collection(Collections.STRATERGY),

            # Standards collection
            'standards': mongodb_manager.get_collection(Collections.STANDARDS),

            # Assets collection
            'assets': mongodb_manager.get_collection(Collections.ASSETS),

            # Logging and Feedback collections
            'logs': mongodb_manager.get_collection(Collections.LOGS),
            'feedback': mongodb_manager.get_collection(Collections.FEEDBACK),

            # Asset Configuration collection
            'asset_configurations': mongodb_manager.get_collection(Collections.ASSET_CONFIGURATIONS),

            # Taxonomy collection (Dynamic overrides)
            'taxonomy': mongodb_manager.get_collection("taxonomy"),

            # Instrument Diagnostics collections
            'instrument_logs': mongodb_manager.get_collection(Collections.INSTRUMENT_LOGS),
            'diagnostic_codes': mongodb_manager.get_collection(Collections.DIAGNOSTIC_CODES),
            'diagnostic_sessions': mongodb_manager.get_collection(Collections.DIAGNOSTIC_SESSIONS),
            'monitor_sources': mongodb_manager.get_collection(Collections.MONITOR_SOURCES),

            # Procurement collection
            'procurement_devices': mongodb_manager.get_collection(Collections.PROCUREMENT_DEVICES),

            # Hybrid Agentic Memory
            'user_hybrid_memories': mongodb_manager.get_collection(Collections.USER_HYBRID_MEMORIES),

            # Search session context (spec sidebar SSOT)
            'search_session_context': mongodb_manager.get_collection(Collections.SEARCH_SESSION_CONTEXT),

            # Holistic gate session context
            'holistic_context': mongodb_manager.get_collection(Collections.HOLISTIC_CONTEXT),

            # Full conversation/chat turn history
            'conversation_memory': mongodb_manager.get_collection(Collections.CONVERSATION_MEMORY),

            # Embedded conversation episodes (episodic recall on past exchanges)
            'conversation_episodes': mongodb_manager.get_collection(Collections.CONVERSATION_EPISODES),

            # Auto-indexing audit queue (missing product type tracking)
            'missing_product_types': mongodb_manager.get_collection(Collections.MISSING_PRODUCT_TYPES),

            # Credits system
            'user_credits': mongodb_manager.get_collection(Collections.USER_CREDITS),
            'credit_transactions': mongodb_manager.get_collection(Collections.CREDIT_TRANSACTIONS),
            'credit_workflow_runs': mongodb_manager.get_collection(Collections.CREDIT_WORKFLOW_RUNS),
        }
    }

def _safe_create_index(collection, keys, **kwargs):
    """
    Safely create an index, handling CosmosDB conflicts gracefully.
    CosmosDB adds 'enableOrderedIndex' which can cause conflicts with existing indexes.
    """
    try:
        collection.create_index(keys, **kwargs)
    except Exception as e:
        error_str = str(e)
        # Handle CosmosDB index conflict:
        #   code 86  = IndexKeySpecsConflict (index exists with different options)
        #   code 11000 = DuplicateKey (index with same name already exists)
        if (
            "IndexKeySpecsConflict" in error_str
            or "IndexOptionsConflict" in error_str
            or "code': 85" in error_str
            or "'code': 85" in error_str
            or "code': 86" in error_str
            or "same name as the requested index" in error_str
            or "already exists with a different name" in error_str
            or "code': 11000" in error_str
            or "'code': 11000" in error_str
            or "DuplicateKey" in error_str
        ):
            index_name = kwargs.get('name', str(keys))
            logger.debug(f"Index '{index_name}' already exists (CosmosDB), skipping")
        else:
            raise


def ensure_indexes():
    """Create necessary indexes for efficient querying"""
    try:
        conn = get_mongodb_connection()
        collections = conn['collections']
        db = conn['database']

        # Specs collection indexes
        _safe_create_index(collections['specs'], [("product_type", 1)])
        _safe_create_index(collections['specs'], [("metadata.product_type", 1)])
        # Index for normalized product type used in Strategy 2 of get_schema_from_mongodb()
        _safe_create_index(collections['specs'], [("metadata.normalized_product_type", 1)])

        # Vendors collection indexes
        _safe_create_index(collections['vendors'], [("product_type", 1), ("vendor", 1)])
        _safe_create_index(collections['vendors'], [("metadata.product_type", 1), ("metadata.vendor_name", 1)])
        # Indexes for catalog aggregate queries (product_type regex + unwind/group)
        _safe_create_index(collections['vendors'], [("product_type", 1)], name="idx_vendors_product_type")
        _safe_create_index(collections['vendors'], [("product_type", 1), ("vendor_name", 1)], name="idx_vendors_pt_vn")
        _safe_create_index(collections['vendors'], [("vendor_name", 1)], name="idx_vendors_vendor_name")

        # User projects collection indexes
        # P1.x FIX: Using _safe_create_index for CosmosDB compatibility
        _safe_create_index(collections['user_projects'], [
            ("user_id", 1),
            ("project_status", 1),
            ("updated_at", -1)
        ])
        _safe_create_index(collections['user_projects'], [
            ("user_id", 1),
            ("project_name", 1)
        ])
        # New index for Azure Blob Storage queries (optional but helpful)
        _safe_create_index(collections['user_projects'], [
            ("blob_info.blobUrl", 1)
        ])
        # Index for storage format to track migration progress
        _safe_create_index(collections['user_projects'], [
            ("storage_format", 1)
        ])

        # Missing product types (auto-indexing audit queue) indexes
        _safe_create_index(collections['missing_product_types'], [
            ("normalized_name", 1)
        ], unique=True)
        _safe_create_index(collections['missing_product_types'], [
            ("status", 1),
            ("search_count", -1)
        ])

        # Per-model benchmark leaderboard aggregations (group by model/provider
        # over a time window; without these the pipeline collection-scans)
        _safe_create_index(db["benchmark_llm_usage"], [("model_name", 1), ("timestamp", -1)])
        _safe_create_index(db["benchmark_llm_usage"], [("provider", 1), ("timestamp", -1)])
        _safe_create_index(db["benchmark_llm_usage"], [("agent_type", 1), ("timestamp", -1)])
        _safe_create_index(db["benchmark_runs"], [("source", 1), ("started_at", -1)])

        # Credits system indexes
        _safe_create_index(collections['user_credits'], [("user_id", 1)], unique=True)
        _safe_create_index(collections['credit_transactions'], [("user_id", 1), ("timestamp", -1)])
        _safe_create_index(collections['credit_transactions'], [("stream_id", 1)])
        _safe_create_index(collections['credit_workflow_runs'], [("stream_id", 1)], unique=True)
        _safe_create_index(collections['credit_workflow_runs'], [("user_id", 1), ("created_at", -1)])
        _safe_create_index(collections['credit_workflow_runs'], [("status", 1)])

        # Persisted P&ID drawings: one document per user + solution session
        _safe_create_index(db[Collections.PID_GRAPHS], [("user_id", 1), ("session_id", 1)],
                           unique=True, name="idx_pid_graphs_user_session")

        # Advanced specifications cache indexes
        # Index on normalized_product_type which is what the queries use
        _safe_create_index(collections['advanced_specifications'], [
            ("normalized_product_type", 1)
        ], unique=True)
        _safe_create_index(
            collections['advanced_specifications'],
            "created_at",
            expireAfterSeconds=60 * 60 * 24 * 30  # ~30 days
        )

        # Images cache indexes
        _safe_create_index(collections['images'], [
            ("vendor_name_normalized", 1),
            ("model_family_normalized", 1)
        ], unique=True)
        _safe_create_index(
            collections['images'],
            "created_at",
            expireAfterSeconds=60 * 60 * 24 * 90  # ~90 days
        )

        # Generic images cache indexes
        _safe_create_index(
            collections['generic_images'],
            [("product_type_normalized", 1)],
            name="idx_generic_product_type",
            unique=True
        )
        _safe_create_index(
            collections['generic_images'],
            "created_at",
            expireAfterSeconds=60 * 60 * 24 * 90  # ~90 days
        )

        # Vendor logos cache indexes
        _safe_create_index(
            collections['vendor_logos'],
            "vendor_name_normalized",
            unique=True
        )
        _safe_create_index(
            collections['vendor_logos'],
            "created_at",
            expireAfterSeconds=60 * 60 * 24 * 90  # ~90 days
        )

        # Strategy collection indexes
        _safe_create_index(collections['stratergy'], [
            ("user_id", 1),
            ("uploaded_at", -1)
        ])
        _safe_create_index(collections['stratergy'], [
            ("user_id", 1),
            ("filename", 1)
        ])

        # Standards collection indexes
        _safe_create_index(collections['standards'], [
            ("user_id", 1),
            ("uploaded_at", -1)
        ])
        _safe_create_index(collections['standards'], [
            ("user_id", 1),
            ("filename", 1)
        ])
        _safe_create_index(collections['standards'], [
            ("user_id", 1),
            ("data.category", 1)
        ])

        # Assets collection indexes
        _safe_create_index(collections['assets'], [
            ("user_id", 1),
            ("uploaded_at", -1)
        ])
        _safe_create_index(collections['assets'], [
            ("user_id", 1),
            ("filename", 1)
        ])

        # Logs collection indexes (for user interaction logs)
        _safe_create_index(collections['logs'], [
            ("user_id", 1),
            ("session_id", 1)
        ], unique=True)  # One log entry per user per session
        _safe_create_index(collections['logs'], [
            ("user_id", 1),
            ("last_updated", -1)
        ])  # For querying recent user activity
        _safe_create_index(collections['logs'], [
            ("session_id", 1)
        ])  # For querying specific session
        # P1.6: TTL index to prevent unbounded storage growth
        _safe_create_index(
            collections['logs'],
            "last_updated",
            name="logs_ttl_30d",
            expireAfterSeconds=60 * 60 * 24 * 30  # Auto-delete logs older than 30 days
        )

        # Feedback collection indexes (for user feedback on recommendations)
        _safe_create_index(collections['feedback'], [
            ("user_id", 1),
            ("timestamp", -1)
        ])  # For querying user's feedback history
        _safe_create_index(collections['feedback'], [
            ("vendor_name", 1),
            ("feedback_type", 1)
        ])  # For querying feedback by vendor
        _safe_create_index(collections['feedback'], [
            ("item_type", 1),
            ("category", 1)
        ])  # For querying feedback by product type
        _safe_create_index(collections['feedback'], [
            ("feedback_type", 1),
            ("timestamp", -1)
        ])  # For querying positive/negative feedback
        # P1.6: TTL index to prevent unbounded storage growth
        _safe_create_index(
            collections['feedback'],
            "timestamp",
            name="feedback_ttl_90d",
            expireAfterSeconds=60 * 60 * 24 * 90  # Auto-delete feedback older than 90 days
        )
        _safe_create_index(collections['feedback'], [
            ("project_id", 1)
        ])  # For querying feedback by project
        _safe_create_index(collections['feedback'], [
            ("sentiment_analysis.detected_sentiment", 1)
        ])  # For querying by detected sentiment
        _safe_create_index(collections['feedback'], [
            ("sentiment_analysis.discrepancy", 1)
        ])  # For finding discrepancies between user rating and detected sentiment

        # User sessions collection indexes (for session analytics)
        user_sessions = db["user_sessions"]
        _safe_create_index(user_sessions, [
            ("user_id", 1),
            ("session_id", 1)
        ], unique=True)  # Unique constraint on user_id + session_id
        _safe_create_index(user_sessions, [
            ("user_id", 1),
            ("start_time", -1)
        ])  # For querying user sessions sorted by time
        _safe_create_index(user_sessions, [
            ("is_active", 1),
            ("last_activity", -1)
        ])  # For finding active sessions
        _safe_create_index(user_sessions, [
            ("start_time", -1)
        ])  # For time-based queries
        # TTL index for user sessions
        _safe_create_index(
            user_sessions,
            "start_time",
            name="start_time_ttl_90d",
            expireAfterSeconds=60 * 60 * 24 * 90  # Auto-delete sessions older than 90 days
        )

        # Endpoint statistics collection indexes
        endpoint_stats = db["endpoint_statistics"]
        _safe_create_index(endpoint_stats, [
            ("endpoint", 1),
            ("timestamp", -1)
        ])  # For querying specific endpoint over time
        _safe_create_index(endpoint_stats, [
            ("timestamp", -1)
        ])  # For time-based queries
        _safe_create_index(endpoint_stats, [
            ("is_success", 1),
            ("timestamp", -1)
        ])  # For filtering by success/failure
        _safe_create_index(endpoint_stats, [
            ("status_code", 1),
            ("timestamp", -1)
        ])  # For filtering by status code
        # TTL index
        _safe_create_index(
            endpoint_stats,
            "timestamp",
            name="timestamp_ttl_30d",
            expireAfterSeconds=60 * 60 * 24 * 30  # Auto-delete records older than 30 days
        )

        # Query performance collection indexes
        query_perf = db["query_performance"]
        _safe_create_index(query_perf, [
            ("collection", 1),
            ("timestamp", -1)
        ])  # For querying specific collection over time
        _safe_create_index(query_perf, [
            ("timestamp", -1)
        ])  # For time-based queries
        _safe_create_index(query_perf, [
            ("execution_time_ms", -1)
        ])  # For finding slowest queries
        _safe_create_index(query_perf, [
            ("is_slow", 1),
            ("timestamp", -1)
        ])  # For filtering slow queries
        # TTL index
        _safe_create_index(
            query_perf,
            "timestamp",
            name="timestamp_ttl_30d",
            expireAfterSeconds=60 * 60 * 24 * 30  # Auto-delete records older than 30 days
        )

        # Storage metrics collection indexes
        storage_metrics_coll = db["storage_metrics"]
        _safe_create_index(storage_metrics_coll, [
            ("timestamp", -1)
        ])  # For time-based queries
        # TTL index
        _safe_create_index(
            storage_metrics_coll,
            "timestamp",
            name="timestamp_ttl_90d",
            expireAfterSeconds=60 * 60 * 24 * 90  # Auto-delete records older than 90 days
        )

        # LLM Usage collection indexes (for token tracking)
        llm_usage_coll = db["llm_usage"]
        _safe_create_index(llm_usage_coll, [
            ("user_id", 1),
            ("timestamp", -1)
        ])  # For querying user's usage history sorted by time
        _safe_create_index(llm_usage_coll, [
            ("timestamp", -1)
        ])  # For time-based queries
        _safe_create_index(llm_usage_coll, [
            ("user_id", 1),
            ("agent_type", 1)
        ])  # For usage breakdown by agent
        _safe_create_index(llm_usage_coll, [
            ("user_id", 1),
            ("feature_type", 1)
        ])  # For usage breakdown by feature
        _safe_create_index(llm_usage_coll, [
            ("provider", 1),
            ("model_name", 1)
        ])  # For usage breakdown by model
        # Drop old TTL index if it exists (no longer expiring usage data)
        try:
            llm_usage_coll.drop_index("timestamp_ttl_90d")
        except Exception:
            pass  # Index doesn't exist, nothing to do

        # GridFS indexes removed as they are no longer used

        # ======== BENCHMARK COLLECTION INDEXES ========
        # Benchmark data is stored separately from production usage. Runs/results/
        # usage auto-expire after 180 days via TTL indexes.
        benchmark_runs = db["benchmark_runs"]
        _safe_create_index(benchmark_runs, [("run_id", 1)], unique=True)
        _safe_create_index(benchmark_runs, [("suite_key", 1), ("started_at", -1)])
        _safe_create_index(benchmark_runs, [("status", 1)])
        _safe_create_index(
            benchmark_runs, "started_at", name="started_at_ttl_180d",
            expireAfterSeconds=60 * 60 * 24 * 180,
        )

        benchmark_results = db["benchmark_results"]
        _safe_create_index(benchmark_results, [("run_id", 1), ("test_id", 1)])
        _safe_create_index(benchmark_results, [("run_id", 1), ("status", 1)])
        _safe_create_index(
            benchmark_results, "executed_at", name="executed_at_ttl_180d",
            expireAfterSeconds=60 * 60 * 24 * 180,
        )

        benchmark_llm_usage = db["benchmark_llm_usage"]
        _safe_create_index(benchmark_llm_usage, [("run_id", 1), ("test_id", 1)])
        _safe_create_index(
            benchmark_llm_usage, "timestamp", name="timestamp_ttl_180d",
            expireAfterSeconds=60 * 60 * 24 * 180,
        )

        # ======== ASSET CONFIGURATION COLLECTION INDEXES ========
        _safe_create_index(collections['asset_configurations'], [
            ("user_id", 1)
        ])  # All configs for a user
        _safe_create_index(collections['asset_configurations'], [
            ("configuration_id", 1)
        ], unique=True)  # Unique configuration identifier
        _safe_create_index(collections['asset_configurations'], [
            ("user_id", 1),
            ("updated_at", -1)
        ])  # User's configs sorted by most recent

        # ======== INSTRUMENT DIAGNOSTICS COLLECTIONS INDEXES ========
        # For instrument log analysis and diagnostic capabilities

        # Instrument logs collection indexes (time-series readings & events)
        _safe_create_index(collections['instrument_logs'], [
            ("user_id", 1),
            ("asset_id", 1),
            ("timestamp", -1)
        ])  # Primary query pattern: user's instrument logs by time
        _safe_create_index(collections['instrument_logs'], [
            ("user_id", 1),
            ("tag_number", 1),
            ("timestamp", -1)
        ])  # Query by instrument tag
        _safe_create_index(collections['instrument_logs'], [
            ("user_id", 1),
            ("log_type", 1),
            ("timestamp", -1)
        ])  # Filter by log type (reading, alarm, event)
        _safe_create_index(collections['instrument_logs'], [
            ("user_id", 1),
            ("severity", 1)
        ])  # Filter by severity level
        _safe_create_index(collections['instrument_logs'], [
            ("user_id", 1),
            ("is_anomaly", 1),
            ("timestamp", -1)
        ])  # Quick access to anomalies
        # Index for anomaly detector background polling (source + ingested_at)
        _safe_create_index(collections['instrument_logs'], [
            ("source", 1),
            ("ingested_at", 1)
        ])  # _poll_instrument_logs queries by source + ingested_at (no user_id)
        _safe_create_index(collections['instrument_logs'], [
            ("ingested_at", 1)
        ])  # Fallback for ingested_at-only queries
        # TTL index for instrument logs - keep for 365 days
        _safe_create_index(
            collections['instrument_logs'],
            "timestamp",
            name="timestamp_ttl_365d",
            expireAfterSeconds=60 * 60 * 24 * 365  # Auto-delete logs older than 1 year
        )

        # Diagnostic codes collection indexes (failure codes & troubleshooting)
        _safe_create_index(collections['diagnostic_codes'], [
            ("code", 1)
        ], unique=True)  # Unique diagnostic code
        _safe_create_index(collections['diagnostic_codes'], [
            ("manufacturer", 1),
            ("instrument_type", 1)
        ])  # Filter by manufacturer/type
        _safe_create_index(collections['diagnostic_codes'], [
            ("category", 1)
        ])  # Filter by category (pressure, flow, level, etc.)
        _safe_create_index(collections['diagnostic_codes'], [
            ("severity", 1)
        ])  # Filter by severity level

        # Diagnostic sessions collection indexes (analysis results)
        _safe_create_index(collections['diagnostic_sessions'], [
            ("user_id", 1),
            ("created_at", -1)
        ])  # User's diagnostic sessions by time
        _safe_create_index(collections['diagnostic_sessions'], [
            ("user_id", 1),
            ("asset_id", 1)
        ])  # Sessions for specific asset
        _safe_create_index(collections['diagnostic_sessions'], [
            ("session_id", 1)
        ], unique=True)  # Unique session identifier
        _safe_create_index(collections['diagnostic_sessions'], [
            ("status", 1)
        ])  # Filter by status (pending, completed, failed)
        # TTL index for diagnostic sessions - keep for 180 days
        _safe_create_index(
            collections['diagnostic_sessions'],
            "created_at",
            name="created_at_ttl_180d",
            expireAfterSeconds=60 * 60 * 24 * 180  # Auto-delete sessions older than 180 days
        )

        # Monitor sources collection indexes
        _safe_create_index(collections['monitor_sources'], [("user_id", 1), ("created_at", -1)])
        _safe_create_index(collections['monitor_sources'], [("user_id", 1), ("path", 1)], unique=True)
        _safe_create_index(collections['monitor_sources'], [("enabled", 1)])

        # User hybrid memories collection indexes
        _safe_create_index(collections['user_hybrid_memories'], [("user_id", 1)], unique=True)

        # Search session context — one doc per search session, TTL on expires_at
        search_ctx = collections['search_session_context']
        _safe_create_index(search_ctx, [("session_id", 1)], unique=True)
        _safe_create_index(search_ctx, [("updated_at", -1)])
        _safe_create_index(
            search_ctx,
            "expires_at",
            name="search_context_expires_ttl",
            expireAfterSeconds=0,
        )

        # Conversation episodes — many docs per session, TTL on expires_at
        episodes = collections['conversation_episodes']
        _safe_create_index(episodes, [("user_id", 1)])
        _safe_create_index(episodes, [("session_id", 1)])
        _safe_create_index(episodes, [("project_id", 1)])
        _safe_create_index(episodes, [("created_at", -1)])
        _safe_create_index(
            episodes,
            "expires_at",
            name="conversation_episodes_expires_ttl",
            expireAfterSeconds=0,
        )

        # Holistic gate context — one doc per (user_id, session_id), TTL on
        # expires_at. Composite unique index (NOT session_id alone): two
        # different authenticated users -- or an authenticated user and an
        # anonymous caller -- sharing the same session_id (e.g. both hitting
        # the "default" fallback) must get separate documents, never overwrite
        # each other. See common/ai/memory/holistic.py for the query pattern.
        holistic_ctx = collections['holistic_context']
        _safe_create_index(holistic_ctx, [("session_id", 1), ("user_id", 1)], unique=True)
        _safe_create_index(holistic_ctx, [("updated_at", -1)])
        _safe_create_index(
            holistic_ctx,
            "expires_at",
            name="holistic_context_expires_ttl",
            expireAfterSeconds=0,
        )

        # Conversation memory — full chat/search turn history (common/ai/memory/core.py).
        # TTL is PARTIAL: it only applies to docs where is_saved=False, so sessions
        # stamped as belonging to a saved project (mark_session_saved) are exempt
        # from expiry entirely until the project is deleted (unmark_session_saved
        # re-arms the countdown). Note: core.py writes last_updated as a native UTC
        # datetime — Mongo's TTL monitor silently ignores string-typed date fields,
        # so do not revert that to isoformat() strings.
        conv_mem = collections['conversation_memory']
        _safe_create_index(conv_mem, [("session_id", 1)], unique=True, name="idx_conversation_session_id")
        _safe_create_index(
            conv_mem,
            "last_updated",
            name="conversation_memory_ttl",
            expireAfterSeconds=_CONVERSATION_MEMORY_TTL_SECONDS,
            partialFilterExpression={"is_saved": {"$eq": False}},
        )

        logger.info("MongoDB indexes created successfully for all active collections")

    except Exception as e:
        logger.error(f"Failed to create MongoDB indexes: {e}")
        # Do not re-raise — a single index conflict should not abort all remaining index creation

# P0.x FIX: Initialization is now handled by create_db() in main.py / gunicorn.conf.py
# ensure_indexes()


# =========================================================================
# === RESTRUCTURED 5-LAYER HIERARCHY (separate 'Restructured' database) ===
# =========================================================================
# The restructured product index lives in its own database. Nodes are keyed by
# `_id` = deterministic UUID, linked by `parent_id`. Levels: L0..L4 plus the
# specification system (SPEC_GROUP / SPEC_DEFINITION / NODE_SPEC).

RESTRUCTURED_DATABASE = os.getenv("RESTRUCTURED_DATABASE", "Restructured")


class RestructuredCollections:
    """Collection names in the Restructured database."""
    # Runtime 5-tier source = the clean catalog rebuild (`catalog_hierarchy`);
    # override with RESTRUCTURED_HIERARCHY_COLLECTION (e.g. "unified_product_hierarchy").
    HIERARCHY = os.getenv("RESTRUCTURED_HIERARCHY_COLLECTION", "catalog_hierarchy")
    L0 = "L0"            # Instrument / Category
    L1 = "L1"            # Product Type (equipment / accessory)
    L2 = "L2"            # Sub-category
    L3 = "L3"            # Model Family
    L4 = "L4"            # Vendor Product
    SPEC_GROUP = "SPEC_GROUP"
    SPEC_DEFINITION = "SPEC_DEFINITION"
    NODE_SPEC = "NODE_SPEC"
    VENDOR = "VENDOR"   # standalone vendor entity; L3/L4.vendor -> VENDOR._id (SUPPLIES_BY)

    LEVELS = ("L0", "L1", "L2", "L3", "L4")


def get_restructured_db() -> Database:
    """Get the Restructured database.

    Uses the dedicated ``restructured_client`` (RESTRUCTURED_DB_URI env var) when
    the hierarchy lives on a separate cluster; falls back to the main client for
    single-cluster deployments.
    """
    return mongodb_manager.restructured_client[RESTRUCTURED_DATABASE]


def get_restructured_connection() -> dict:
    """Connection components for the Restructured database."""
    db = get_restructured_db()
    rc = RestructuredCollections
    names = [rc.HIERARCHY, rc.L0, rc.L1, rc.L2, rc.L3, rc.L4,
             rc.SPEC_GROUP, rc.SPEC_DEFINITION, rc.NODE_SPEC, rc.VENDOR]
    return {"database": db, "collections": {n: db[n] for n in names}}


def ensure_restructured_indexes():
    """Create indexes for the Restructured 5-layer hierarchy + spec system.

    `_id` is the UUID, so it already has the default unique index everywhere —
    we only add the traversal / lookup indexes.
    """
    try:
        db = get_restructured_db()
        rc = RestructuredCollections

        # Flat hierarchy — traversal by parent_id, filter by level / node_type / key
        H = db[rc.HIERARCHY]
        _safe_create_index(H, [("parent_id", 1)], name="ix_parent_id")
        _safe_create_index(H, [("level", 1)], name="ix_level")
        _safe_create_index(H, [("metadata.node_type", 1)], name="ix_node_type")
        _safe_create_index(H, [("key", 1)], name="ix_key")
        _safe_create_index(H, [("level", 1), ("parent_id", 1)], name="ix_level_parent")

        # Relational level views — FK is parent_id
        for lv in rc.LEVELS:
            c = db[lv]
            _safe_create_index(c, [("parent_id", 1)], name="ix_parent_id")
            _safe_create_index(c, [("metadata.node_type", 1)], name="ix_node_type")

        # Specification system
        sg = db[rc.SPEC_GROUP]
        _safe_create_index(sg, [("group_code", 1)], name="ix_group_code")

        sd = db[rc.SPEC_DEFINITION]
        _safe_create_index(sd, [("spec_code", 1)], name="ix_spec_code")
        _safe_create_index(sd, [("group_id", 1)], name="ix_group_id")
        _safe_create_index(sd, [("is_standard", 1)], name="ix_is_standard")

        ns = db[rc.NODE_SPEC]
        _safe_create_index(ns, [("source_node_id", 1)], name="ix_ns_source")
        _safe_create_index(ns, [("spec_code", 1)], name="ix_ns_code")
        _safe_create_index(ns, [("spec_def_id", 1)], name="ix_ns_specdef")
        _safe_create_index(ns, [("source_node_id", 1), ("value", 1)], name="ix_ns_source_value")
        _safe_create_index(ns, [("is_standard", 1), ("source_node_id", 1)], name="ix_ns_standard")

        # Vendor entity — lookup by code / name (SUPPLIES_BY = L3/L4.vendor == VENDOR._id)
        vc = db[rc.VENDOR]
        _safe_create_index(vc, [("vendor_code", 1)], name="ix_vendor_code")
        _safe_create_index(vc, [("vendor_name", 1)], name="ix_vendor_name")

        logger.info("Restructured indexes created successfully")
    except Exception as e:
        logger.error(f"Failed to create Restructured indexes: {e}")
