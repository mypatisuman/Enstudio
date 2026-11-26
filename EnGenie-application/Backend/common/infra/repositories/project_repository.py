"""
MongoDB Project Management Module
Handles project storage and retrieval in MongoDB using Azure Blob Storage
"""
import json
import logging
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from common.infra.azure_blob import azure_blob_manager
from common.infra.mongodb_utils import MongoDBFileManager


class MongoProjectManager:
    """Manages project operations in MongoDB with Azure Blob Storage"""

    def __init__(self):
        self.file_manager = MongoDBFileManager()
        self.collection_name = 'user_projects'
        self.logger = logging.getLogger(__name__)

    def save_project(self, user_id: str, project_data: dict[str, Any]) -> dict[str, Any]:
        """
        Save or update a project in MongoDB using GridFS

        Args:
            user_id: ID of the user who owns the project
            project_data: Project data to save

        Returns:
            Dictionary with project ID and metadata
        """
        try:
            project_id = project_data.get('project_id')
            current_time = datetime.now(UTC)

            # Ensure detected product type is used, and avoid accidentally saving project_name as product_type
            project_name = (project_data.get('project_name') or '').strip()
            detected_product_type = (project_data.get('detected_product_type') or '').strip()
            incoming_product_type = (project_data.get('product_type') or '').strip()

            # Discard sentinel/placeholder values that carry no real information
            _INVALID_PRODUCT_TYPES = {'unknown', 'unknownproduct', 'none', ''}
            if detected_product_type and detected_product_type.lower() not in _INVALID_PRODUCT_TYPES:
                product_type = detected_product_type
            elif incoming_product_type and incoming_product_type.lower() not in _INVALID_PRODUCT_TYPES:
                # If incoming product_type exactly matches project_name, ignore it
                if project_name and incoming_product_type.lower() == project_name.lower():
                    self.logger.warning(f"Incoming product_type matches project_name ('{incoming_product_type}'). Clearing product_type to avoid incorrect storage for user {user_id}.")
                    product_type = ''
                else:
                    product_type = incoming_product_type
            else:
                self.logger.info(f"[SAVE_PROJECT] product_type resolved to empty (incoming='{incoming_product_type}', detected='{detected_product_type}') for user {user_id}")
                product_type = ''

            # Build complete project data for GridFS storage (no serialization needed)
            complete_project_data = {
                'project_name': project_data.get('project_name', ''),
                'project_description': project_data.get('project_description', ''),
                'initial_requirements': project_data.get('initial_requirements', ''),
                'product_type': product_type,
                'source_page': project_data.get('source_page', ''),  # Track which page created this project
                'pricing': project_data.get('pricing', {}),
                'identified_instruments': project_data.get('identified_instruments', []),
                'identified_accessories': project_data.get('identified_accessories', []),
                'awaiting_single_item_confirmation': project_data.get('awaiting_single_item_confirmation', False),
                'search_tabs': project_data.get('search_tabs', []),
                'conversation_histories': project_data.get('conversation_histories', {}),
                'collected_data': project_data.get('collected_data', {}),
                'generic_images': project_data.get('generic_images', {}),
                'project_chat_messages': project_data.get('project_chat_messages', []),  # Project page chat messages
                'feedback_entries': project_data.get('feedback_entries', project_data.get('feedback', [])),
                'current_step': project_data.get('current_step', ''),
                'active_tab': project_data.get('active_tab', ''),
                'analysis_results': project_data.get('analysis_results', {}),
                'field_descriptions': project_data.get('field_descriptions', {}),
                'workflow_position': project_data.get('workflow_position', {}),
                'designed_solution': project_data.get('designed_solution', None),
                'user_interactions': project_data.get('user_interactions', {}),
                'embedded_media': project_data.get('embedded_media', {}),
                'project_instance_id': project_data.get('project_instance_id', ''),  # Save project instance ID for session isolation
                'project_metadata': {
                    'schema_version': '2.0',
                    'storage_format': 'azure_blob',
                    'data_structure_description': 'Complete project state stored in Azure Blob Storage',
                    'supported_features': ['multi_tab_search', 'conversation_persistence', 'state_restoration', 'analysis_results'],
                    'last_updated_by': 'ai_product_recommender_system'
                }
            }

            # Convert to JSON bytes for Azure Blob storage
            # Prefer the gate-consolidated requirement (original + chat-supplied
            # answers, from conversation memory) over the frontend's requirements
            # field — otherwise every requirement detail the user supplied in chat
            # is invisible to episodic recall. Best-effort; original preserved.
            saved_session_id = (project_data.get('session_id')
                                or project_data.get('project_instance_id') or '')
            if saved_session_id and not complete_project_data.get('consolidated_requirements'):
                try:
                    from common.ai.memory import get_latest_consolidated_requirement
                    consolidated = get_latest_consolidated_requirement(saved_session_id)
                    if consolidated:
                        complete_project_data['consolidated_requirements'] = consolidated
                        self.logger.info(
                            f"[SAVE_PROJECT] Using gate-consolidated requirement "
                            f"({len(consolidated)} chars) for the episodic signature")
                except Exception as e:
                    self.logger.warning(f"[SAVE_PROJECT] Consolidated-requirement lookup failed: {e}")

            project_json = json.dumps(complete_project_data, ensure_ascii=False, indent=2)
            project_bytes = project_json.encode('utf-8')

            # Calculate counts for metadata (optimization: avoid loading blobs in list view)
            instruments_count = len(complete_project_data.get('identified_instruments', []))
            accessories_count = len(complete_project_data.get('identified_accessories', []))
            search_tabs_count = len(complete_project_data.get('search_tabs', []))
            workflow_position = complete_project_data.get('workflow_position', {})

            # Compute episodic fingerprint: a semantic embedding of the project's
            # defining input so a future (possibly reworded) request can be matched
            # back to this saved project. Stored on the metadata doc for fast lookup.
            signature_text = self._build_signature_text(complete_project_data)
            input_embedding = self._compute_signature_embedding(signature_text)

            # Second semantic context: the DESIGNED SOLUTION. A returning user often
            # describes the solution ("cascade pressure control with split-range
            # level...") rather than re-typing requirements — that wording lives in
            # the design, not the input signature. Embedded compactly (the model
            # truncates at ~256 tokens) and matched with max(input, design) scoring.
            design_signature_text = self._build_design_signature_text(
                complete_project_data.get('designed_solution') or {})
            design_embedding = self._compute_signature_embedding(design_signature_text)

            # Log the product_type we plan to save for debugging
            self.logger.info(f"Saving project to Azure Blob - detected_product_type='{detected_product_type}' resolved_product_type='{product_type}' for user {user_id}")

            project_instance_id = (project_data.get('project_instance_id') or '').strip()

            # If no project_id is provided, but a project_instance_id is provided,
            # check if a project with this project_instance_id already exists for the user.
            if not project_id and project_instance_id:
                existing_by_instance = self.file_manager.db[self.collection_name].find_one({
                    'project_instance_id': project_instance_id,
                    'user_id': str(user_id),
                    'project_status': 'active'
                })
                if existing_by_instance:
                    project_id = str(existing_by_instance['_id'])
                    self.logger.info(f"[SAVE_PROJECT] Found existing project {project_id} matching project_instance_id {project_instance_id}. Promoting to update flow.")

            if project_id:
                # Update existing project
                try:
                    object_id = ObjectId(project_id)
                    existing_project = self.file_manager.db[self.collection_name].find_one({
                        '_id': object_id,
                        'user_id': str(user_id)
                    })

                    if not existing_project:
                        raise ValueError("Project not found or access denied")

                    # Check for duplicate project name if name changed
                    if existing_project.get('project_name', '').strip().lower() != project_name.lower():
                        existing_duplicate = self.file_manager.db[self.collection_name].find_one({
                            'user_id': str(user_id),
                            'project_name': project_name,
                            'project_status': 'active'
                        })

                        if existing_duplicate and str(existing_duplicate.get('_id')) != project_id:
                            self.logger.warning(f"Duplicate project name '{project_name}' found for user {user_id}")
                            raise ValueError(f"Project name '{project_name}' already exists. Please choose a different name.")

                    # Upload new data to Azure Blob Storage
                    blob_info = azure_blob_manager.upload_project_data(
                        project_json_bytes=project_bytes,
                        user_id=user_id,
                        project_id=project_id,
                        content_type='application/json'
                    )

                    # Update metadata document in collection with blob info and counts
                    metadata_doc = {
                        'user_id': str(user_id),
                        'project_name': project_name,
                        'project_description': project_data.get('project_description', ''),
                        'product_type': product_type,
                        'source_page': project_data.get('source_page', ''),
                        'blob_info': blob_info,  # NEW: Store blob metadata
                        'storage_format': 'azure_blob',
                        'project_status': 'active',
                        'updated_at': current_time,
                        'file_size': len(project_bytes),
                        # NEW: Store counts in metadata for efficient list view
                        'instruments_count': instruments_count,
                        'accessories_count': accessories_count,
                        'search_tabs_count': search_tabs_count,
                        'project_phase': workflow_position.get('project_phase', 'unknown'),
                        'project_instance_id': project_instance_id,  # Save instance ID in metadata for lookups
                        # Episodic recall fingerprints (requirements + designed solution)
                        'input_signature_text': signature_text,
                        'input_embedding': input_embedding,
                        'design_signature_text': design_signature_text,
                        'design_embedding': design_embedding
                    }

                    result = self.file_manager.db[self.collection_name].update_one(
                        {'_id': object_id, 'user_id': str(user_id)},
                        {'$set': metadata_doc}
                    )

                    if result.matched_count == 0:
                        raise ValueError("Failed to update project")

                    # Delete old blob after successful update (cleanup)
                    old_blob_info = existing_project.get('blob_info')
                    if old_blob_info:
                        try:
                            container = old_blob_info['container']
                            blob_name = old_blob_info['blobName']
                            blob_client = azure_blob_manager.blob_service_client.get_blob_client(
                                container=container, blob=blob_name
                            )
                            blob_client.delete_blob()
                            self.logger.info(f"Deleted old blob {blob_name} for project {project_id}")
                        except Exception as e:
                            self.logger.warning(f"Failed to delete old blob: {e}")

                    # Also try to delete old GridFS file if it exists (backward compatibility cleanup)
                    old_gridfs_id = existing_project.get('gridfs_file_id')
                    if old_gridfs_id:
                        try:
                            if self.file_manager.gridfs:
                                self.file_manager.gridfs.delete(ObjectId(old_gridfs_id))
                                self.logger.info(f"Deleted old GridFS file {old_gridfs_id} for project {project_id}")
                        except Exception as e:
                            self.logger.warning(f"Failed to delete old GridFS file: {e}")

                    final_project_id = str(object_id)
                    self.logger.info(f"Updated project {final_project_id} in Azure Blob for user {user_id}")

                except (ValueError, Exception) as e:
                    self.logger.error(f"Failed to update project {project_id}: {e}")
                    raise
            else:
                # Create new project - first check for duplicate name
                existing_duplicate = self.file_manager.db[self.collection_name].find_one({
                    'user_id': str(user_id),
                    'project_name': project_name,
                    'project_status': 'active'
                })

                if existing_duplicate:
                    self.logger.warning(f"Duplicate project name '{project_name}' found for user {user_id}")
                    raise ValueError(f"Project name '{project_name}' already exists. Please choose a different name.")

                # Upload data to Azure Blob Storage first
                blob_info = azure_blob_manager.upload_project_data(
                    project_json_bytes=project_bytes,
                    user_id=user_id,
                    project_id="new",  # Will be replaced with actual ID after insert
                    content_type='application/json'
                )

                # Create metadata document in collection with blob info and counts
                metadata_doc = {
                    'user_id': str(user_id),
                    'project_name': project_name,
                    'project_description': project_data.get('project_description', ''),
                    'product_type': product_type,
                    'source_page': project_data.get('source_page', ''),
                    'blob_info': blob_info,  # NEW: Store blob metadata
                    'storage_format': 'azure_blob',
                    'project_status': 'active',
                    'created_at': current_time,
                    'updated_at': current_time,
                    'file_size': len(project_bytes),
                    # NEW: Store counts in metadata for efficient list view
                    'instruments_count': instruments_count,
                    'accessories_count': accessories_count,
                    'search_tabs_count': search_tabs_count,
                    'project_phase': workflow_position.get('project_phase', 'unknown'),
                    'project_instance_id': project_instance_id,  # Save instance ID in metadata for lookups
                    # Episodic recall fingerprints (requirements + designed solution)
                    'input_signature_text': signature_text,
                    'input_embedding': input_embedding,
                    'design_signature_text': design_signature_text,
                    'design_embedding': design_embedding
                }

                result = self.file_manager.db[self.collection_name].insert_one(metadata_doc)
                final_project_id = str(result.inserted_id)
                self.logger.info(f"Created new project {final_project_id} in Azure Blob for user {user_id}")

            # Stamp this session's conversation episodes with the saved project so
            # episode matches can surface it in episodic recall. Best-effort.
            if saved_session_id and final_project_id:
                try:
                    from common.ai.memory import link_session_episodes_to_project
                    link_session_episodes_to_project(saved_session_id, final_project_id)
                except Exception as e:
                    self.logger.warning(f"[SAVE_PROJECT] Episode linking failed: {e}")

            return {
                'project_id': final_project_id,
                'project_name': project_name,
                'project_description': project_data.get('project_description', ''),
                'product_type': product_type,
                'pricing': project_data.get('pricing', {}),
                'feedback_entries': project_data.get('feedback_entries', project_data.get('feedback', [])),
                'created_at': metadata_doc.get('created_at', current_time).isoformat(),
                'updated_at': metadata_doc['updated_at'].isoformat(),
                'project_status': metadata_doc['project_status']
            }

        except Exception as e:
            self.logger.error(f"Failed to save project for user {user_id}: {e}")
            raise

    @staticmethod
    def _build_signature_text(project_data: dict[str, Any]) -> str:
        """
        Build the text that defines a project's semantic identity for episodic recall.

        Combines the user-facing name, product type and the original requirements so
        that a reworded or differently-structured future request describing the same
        intent embeds near this project.
        """
        parts = [
            project_data.get('project_name', ''),
            project_data.get('product_type', ''),
            # The consolidated requirement (original + chat-supplied gap answers)
            # carries strictly more signal than the frontend's requirements field.
            project_data.get('consolidated_requirements') or project_data.get('initial_requirements', ''),
            project_data.get('project_description', ''),
        ]
        return ' '.join(p.strip() for p in parts if p and p.strip()).strip()

    @staticmethod
    def _build_design_signature_text(designed_solution: dict[str, Any]) -> str:
        """
        Build the DESIGNED SOLUTION's semantic identity for episodic recall — the
        second matching context alongside the requirements signature.

        Field-prioritized and hard-capped (~900 chars ≈ under the embedding
        model's 256-token truncation): objective first, then design overview,
        component roles (name: purpose), then optimizations if budget remains.
        design_considerations/assumptions are excluded (lowest signal per char).
        """
        if not designed_solution or not isinstance(designed_solution, dict):
            return ''

        budget = 900
        parts: list[str] = []

        def _add(text: str) -> bool:
            nonlocal budget
            text = (text or '').strip()
            if not text or budget <= 0:
                return False
            text = text[:budget]
            parts.append(text)
            budget -= len(text) + 1
            return True

        _add(designed_solution.get('project_objective') or designed_solution.get('projectObjective', ''))
        _add(designed_solution.get('design_overview') or designed_solution.get('designOverview', ''))
        for role in (designed_solution.get('component_roles')
                     or designed_solution.get('componentRoles') or []):
            if isinstance(role, dict):
                name = role.get('name') or role.get('category', '')
                purpose = role.get('purpose', '')
                if not _add(f"{name}: {purpose}" if purpose else str(name)):
                    break
        for opt in designed_solution.get('optimizations') or []:
            if not _add(str(opt)):
                break

        return '\n'.join(parts).strip()

    @staticmethod
    def _compute_signature_embedding(signature_text: str) -> list[float] | None:
        """Embed the signature text, returning None if embedding is unavailable."""
        if not signature_text:
            return None
        try:
            from common.ai.embedding_manager import generate_embedding
            return generate_embedding(signature_text)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to compute project signature embedding: {e}")
            return None

    def build_candidate_from_project_id(self, project_id: str, user_id: str,
                                        similarity: float) -> dict[str, Any] | None:
        """Build a recall-candidate dict (same shape as find_similar_projects
        matches) from a project's metadata doc — used when a CONVERSATION
        EPISODE linked to this project matched the query. Returns None when the
        project is missing/inactive or not owned by the user."""
        try:
            doc = self.file_manager.db[self.collection_name].find_one({
                '_id': ObjectId(project_id),
                'user_id': str(user_id),
                'project_status': 'active',
            })
            if not doc:
                return None
            updated_at = doc.get('updated_at')
            return {
                'project_id': str(doc['_id']),
                'project_name': doc.get('project_name', ''),
                'product_type': doc.get('product_type', ''),
                'similarity': round(float(similarity), 4),
                'matched_on': 'conversation',
                'updated_at': updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
                'instruments_count': doc.get('instruments_count'),
                'accessories_count': doc.get('accessories_count'),
                'search_tabs_count': doc.get('search_tabs_count'),
                'input_signature_text': (doc.get('input_signature_text') or '')[:600],
                'design_signature_text': (doc.get('design_signature_text') or '')[:400],
            }
        except Exception as e:
            self.logger.warning(f"Failed to build recall candidate from project {project_id}: {e}")
            return None

    def find_similar_projects(
        self,
        user_id: str,
        query_text: str,
        threshold: float = 0.78,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Find a user's saved projects whose stored input fingerprint is semantically
        similar to ``query_text`` (handles jumbled wording / different phrasing).

        Args:
            user_id: Owner of the projects to search.
            query_text: The new incoming request to match.
            threshold: Minimum cosine similarity (0-1) to consider a match.
            top_k: Maximum number of matches to return.

        Returns:
            List of match dicts sorted by similarity (highest first), each with
            project_id, project_name, product_type, similarity and updated_at.
        """
        if not user_id or not query_text or not query_text.strip():
            return []

        try:
            from common.ai.embedding_manager import find_most_similar, generate_embedding

            query_embedding = generate_embedding(query_text)
            if not query_embedding:
                return []

            projects_cursor = self.file_manager.db[self.collection_name].find(
                {
                    'user_id': str(user_id),
                    'project_status': 'active',
                    'input_embedding': {'$exists': True, '$ne': None},
                }
            )

            candidate_docs: list[dict[str, Any]] = []
            candidate_embeddings: list[list[float]] = []
            for project in projects_cursor:
                embedding = project.get('input_embedding')
                if embedding:
                    candidate_docs.append(project)
                    candidate_embeddings.append(embedding)

            if not candidate_embeddings:
                return []

            # Raw scores for ALL candidates (threshold=0.0) so the dual-context
            # max() is taken BEFORE thresholding: a project may be recognized by
            # its requirements signature OR its designed-solution signature.
            input_ranked = find_most_similar(query_embedding, candidate_embeddings, threshold=0.0)
            input_sims = {index: float(score) for index, score in input_ranked}

            from common.ai.embedding_manager import cosine_similarity
            combined: list[tuple[int, float, float, float]] = []  # (index, combined, input, design)
            for index, doc in enumerate(candidate_docs):
                input_sim = input_sims.get(index, 0.0)
                design_sim = 0.0
                design_emb = doc.get('design_embedding')
                if design_emb:
                    try:
                        design_sim = float(cosine_similarity(query_embedding, design_emb))
                    except Exception:
                        design_sim = 0.0
                score = max(input_sim, design_sim)
                if score >= threshold:
                    combined.append((index, score, input_sim, design_sim))
            combined.sort(key=lambda t: t[1], reverse=True)

            matches = []
            for index, score, input_sim, design_sim in combined[:top_k]:
                doc = candidate_docs[index]
                updated_at = doc.get('updated_at')
                matched_on = 'design' if design_sim > input_sim else 'requirements'
                self.logger.info(
                    f"Episodic recall candidate '{doc.get('project_name')}' "
                    f"input_sim={round(input_sim, 4)} design_sim={round(design_sim, 4)} matched_on={matched_on}"
                )
                matches.append({
                    'project_id': str(doc['_id']),
                    'project_name': doc.get('project_name', ''),
                    'product_type': doc.get('product_type', ''),
                    'similarity': round(float(score), 4),
                    'matched_on': matched_on,
                    'updated_at': updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
                    # Stored result counts so callers can filter to SUBSTANTIVE projects
                    # (ones that actually have something to open) without loading blobs.
                    # Kept as None when the field is ABSENT (legacy projects saved before
                    # counts existed) so callers can tell "unknown" from a real zero.
                    'instruments_count': doc.get('instruments_count'),
                    'accessories_count': doc.get('accessories_count'),
                    'search_tabs_count': doc.get('search_tabs_count'),
                    # Saved-project signatures (requirements + designed solution) so the
                    # recall agent's LLM verification can compare actual scope, not just
                    # names. Truncated; stripped before the offer reaches the frontend
                    # (see episodic_recall_agent).
                    'input_signature_text': (doc.get('input_signature_text') or '')[:600],
                    'design_signature_text': (doc.get('design_signature_text') or '')[:400],
                })

            self.logger.info(
                f"Episodic recall: found {len(matches)} similar project(s) for user {user_id} "
                f"(query='{query_text[:60]}', threshold={threshold})"
            )
            return matches

        except Exception as e:
            self.logger.error(f"Failed to find similar projects for user {user_id}: {e}")
            return []

    def get_user_projects(self, user_id: str) -> list[dict[str, Any]]:
        """
        Get all projects for a user (metadata only - NO blob loading for performance)

        Args:
            user_id: ID of the user

        Returns:
            List of project summaries with counts from metadata
        """
        try:
            projects_cursor = self.file_manager.db[self.collection_name].find(
                {
                    'user_id': str(user_id),
                    'project_status': 'active'
                },
                no_cursor_timeout=True
            ).sort('updated_at', -1)  # Most recently updated first

            project_list = []
            for project in projects_cursor:
                # Read counts directly from metadata (stored during save)
                # NO BLOB LOADING REQUIRED - Major performance improvement!
                project_summary = {
                    'id': str(project['_id']),
                    'project_name': project.get('project_name', ''),
                    'project_description': project.get('project_description', ''),
                    'product_type': project.get('project_type', ''),
                    'source_page': project.get('source_page', ''),
                    # Read counts from metadata (fast!)
                    'instruments_count': project.get('instruments_count', 0),
                    'accessories_count': project.get('accessories_count', 0),
                    'search_tabs_count': project.get('search_tabs_count', 0),
                    'project_phase': project.get('project_phase', 'unknown'),
                    'conversations_count': 0,  # Not stored in metadata yet
                    'has_analysis': False,  # Not stored in metadata yet
                    'schema_version': '2.0',
                    'storage_format': project.get('storage_format', 'gridfs'),
                    'project_status': project.get('project_status', 'active'),
                    'created_at': project.get('created_at', datetime.now(UTC)).isoformat() if isinstance(project.get('created_at'), datetime) else project.get('created_at', datetime.now(UTC).isoformat()),
                    'updated_at': project.get('updated_at', datetime.now(UTC)).isoformat() if isinstance(project.get('updated_at'), datetime) else project.get('updated_at', datetime.now(UTC).isoformat()),
                    'requirements_preview': '',  # Not needed for list view
                    'file_size': project.get('file_size', 0)
                }
                project_list.append(project_summary)

            self.logger.info(f"Retrieved {len(project_list)} projects for user {user_id} (metadata only - no blob loading)")
            return project_list

        except Exception as e:
            self.logger.error(f"Failed to get projects for user {user_id}: {e}")
            raise

    def get_project_details(self, project_id: str, user_id: str) -> dict[str, Any]:
        """
        Get full project details for loading from Azure Blob Storage or GridFS (backward compatibility)

        Args:
            project_id: ID of the project
            user_id: ID of the user (for security)

        Returns:
            Complete project data
        """
        try:
            object_id = ObjectId(project_id)
            project_meta = self.file_manager.db[self.collection_name].find_one({
                '_id': object_id,
                'user_id': str(user_id)
            })

            if not project_meta:
                raise ValueError("Project not found or access denied")

            # Check storage format
            storage_format = project_meta.get('storage_format', 'gridfs')

            if storage_format == 'azure_blob':
                # New Azure Blob Storage path
                blob_info = project_meta.get('blob_info')
                if not blob_info:
                    raise ValueError("Blob info not found in project metadata")

                # Download from Azure Blob using SDK
                blob_data = azure_blob_manager.download_project_data(blob_info)
                project_data = json.loads(blob_data.decode('utf-8'))

            elif storage_format == 'gridfs':
                # Backward compatibility: Legacy GridFS path
                gridfs_file_id = project_meta.get('gridfs_file_id')
                if not gridfs_file_id:
                    raise ValueError("GridFS file ID not found")

                # Load from GridFS
                if not self.file_manager.gridfs:
                    raise ValueError("GridFS not initialized, cannot load legacy project")

                grid_file = self.file_manager.gridfs.get(ObjectId(gridfs_file_id))
                project_data = json.loads(grid_file.read().decode('utf-8'))

                # Auto-migrate to Azure Blob on load
                self.logger.info(f"Auto-migrating project {project_id} from GridFS to Azure Blob")
                try:
                    # Re-save using new format (will trigger Azure upload)
                    project_data['project_id'] = project_id
                    self.save_project(user_id, project_data)
                    self.logger.info(f"Successfully auto-migrated project {project_id}")
                except Exception as e:
                    self.logger.warning(f"Auto-migration failed for project {project_id}: {e}")
                    # Continue with GridFS data anyway

            else:
                raise ValueError(f"Unknown storage format: {storage_format}")

            # Add metadata fields
            project_data['id'] = str(project_meta['_id'])
            project_data['created_at'] = project_meta.get('created_at', datetime.now(UTC)).isoformat()
            project_data['updated_at'] = project_meta.get('updated_at', datetime.now(UTC)).isoformat()
            project_data['project_status'] = project_meta.get('project_status', 'active')

            self.logger.info(f"Retrieved project {project_id} from {storage_format} for user {user_id}")
            return project_data

        except Exception as e:
            self.logger.error(f"Failed to get project {project_id} for user {user_id}: {e}")
            raise

    def append_feedback_to_project(self, project_id: str, user_id: str, feedback_entry: dict[str, Any]) -> bool:
        """
        Append a feedback entry to a project's feedback_entries array in GridFS
        """
        try:
            # Load current project data
            project_data = self.get_project_details(project_id, user_id)

            # Append feedback
            if 'feedback_entries' not in project_data:
                project_data['feedback_entries'] = []
            project_data['feedback_entries'].append(feedback_entry)

            # Save back (this will update the GridFS file)
            project_data['project_id'] = project_id
            self.save_project(user_id, project_data)

            self.logger.info(f"Appended feedback to project {project_id} for user {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to append feedback to project {project_id}: {e}")
            raise

    def delete_project(self, project_id: str, user_id: str) -> bool:
        """
        Permanently delete a project from MongoDB and Azure Blob Storage (or GridFS for legacy)

        Args:
            project_id: ID of the project
            user_id: ID of the user (for security)

        Returns:
            True if successful
        """
        try:
            object_id = ObjectId(project_id)

            # Get project metadata to find blob/GridFS file
            project_meta = self.file_manager.db[self.collection_name].find_one({
                '_id': object_id,
                'user_id': str(user_id)
            })

            if not project_meta:
                raise ValueError("Project not found or access denied")

            # Delete from Azure Blob if exists
            blob_info = project_meta.get('blob_info')
            if blob_info:
                try:
                    container = blob_info['container']
                    blob_name = blob_info['blobName']
                    blob_client = azure_blob_manager.blob_service_client.get_blob_client(
                        container=container, blob=blob_name
                    )
                    blob_client.delete_blob()
                    self.logger.info(f"Deleted blob {blob_name} for project {project_id}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete blob: {e}")

            # Also delete from GridFS if exists (backward compatibility)
            gridfs_file_id = project_meta.get('gridfs_file_id')
            if gridfs_file_id:
                try:
                    if self.file_manager.gridfs:
                        self.file_manager.gridfs.delete(ObjectId(gridfs_file_id))
                        self.logger.info(f"Deleted GridFS file {gridfs_file_id} for project {project_id}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete GridFS file: {e}")

            # Delete metadata document
            result = self.file_manager.db[self.collection_name].delete_one({
                '_id': object_id,
                'user_id': str(user_id)
            })

            if result.deleted_count == 0:
                raise ValueError("Project not found or access denied")

            # Re-arm the ephemeral TTL for any conversation_memory doc(s) that were
            # exempted by mark_session_saved() when this project was saved — flip
            # is_saved back to False (rather than hard-deleting the chat history)
            # so it resumes the normal 30-day expiry countdown.
            try:
                from common.ai.memory.core import unmark_session_saved
                col = self.file_manager.db.get_collection('conversation_memory')
                if col is not None:
                    for doc in col.find({"project_id": str(project_id)}, {"session_id": 1}):
                        sid = doc.get("session_id")
                        if sid:
                            unmark_session_saved(sid)
            except Exception as e:
                self.logger.warning(f"Failed to re-arm conversation_memory TTL for project {project_id}: {e}")

            self.logger.info(f"Permanently deleted project {project_id} for user {user_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to delete project {project_id} for user {user_id}: {e}")
            raise

    def migrate_project_from_gridfs(self, project_id: str, user_id: str) -> bool:
        """
        Manually migrate a single project from GridFS to Azure Blob Storage

        Args:
            project_id: Project ID to migrate
            user_id: User ID (for security)

        Returns:
            bool: True if successful
        """
        try:
            # Get project metadata
            object_id = ObjectId(project_id)
            project_meta = self.file_manager.db[self.collection_name].find_one({
                '_id': object_id,
                'user_id': str(user_id)
            })

            if not project_meta:
                raise ValueError("Project not found")

            # Check if already migrated
            if project_meta.get('storage_format') == 'azure_blob':
                self.logger.info(f"Project {project_id} already migrated to Azure Blob")
                return True

            # Get GridFS file
            gridfs_file_id = project_meta.get('gridfs_file_id')
            if not gridfs_file_id:
                raise ValueError("No GridFS file found for this project")

            # Load from GridFS
            if not self.file_manager.gridfs:
                raise ValueError("GridFS not initialized, cannot migrate")

            grid_file = self.file_manager.gridfs.get(ObjectId(gridfs_file_id))
            project_bytes = grid_file.read()
            project_data = json.loads(project_bytes.decode('utf-8'))

            # Re-save using new format (will trigger Azure Blob upload)
            project_data['project_id'] = project_id
            self.save_project(user_id, project_data)

            # Note: Old GridFS file will be automatically deleted by save_project
            self.logger.info(f"Successfully migrated project {project_id} from GridFS to Azure Blob")
            return True

        except Exception as e:
            self.logger.error(f"Failed to migrate project {project_id}: {e}")
            raise

# Create global instance
mongo_project_manager = MongoProjectManager()
