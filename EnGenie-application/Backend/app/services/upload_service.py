import base64
import json
import logging
import os
import time
from typing import Any, Optional

# Ensure logging is configured for background threads
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True
    )


def extract_strategy_embeddings_from_csv(file_bytes: bytes, filename: str) -> tuple[bytes, int]:
    """
    Parse CSV strategy file, generate per-column embeddings, and return gzip-compressed payload.

    Returns:
        (gzip_bytes, entry_count) — gzip of {"data": [{col: val, col_embedding: [...]}, ...]}
    """
    import gzip
    import json
    from io import BytesIO

    import pandas as pd

    from common.ai.embedding_manager import generate_embeddings_batch

    logging.info(f"[UPLOAD SERVICE] Parsing strategy CSV: {filename}")
    df = pd.read_csv(BytesIO(file_bytes))
    df.columns = df.columns.str.strip().str.lower()

    column_mapping = {
        'vendor': 'vendor_name', 'vendor name': 'vendor_name', 'manufacturer': 'vendor_name',
        'supplier': 'vendor_name', 'product_category': 'category', 'product category': 'category',
        'product_type': 'category', 'sub_category': 'subcategory', 'sub category': 'subcategory',
        'procurement_strategy': 'strategy', 'procurement strategy': 'strategy',
        'note': 'notes', 'comment': 'notes', 'comments': 'notes',
    }
    df.rename(columns=column_mapping, inplace=True)

    all_columns = list(df.columns)
    column_texts: dict[str, list[str]] = {col: [] for col in all_columns}
    valid_rows = []

    for _, row in df.iterrows():
        non_empty_count = sum(1 for val in row if pd.notna(val) and str(val).strip())
        if non_empty_count >= 2:
            valid_rows.append(row)
            for col in all_columns:
                value = str(row.get(col, '')).strip() if pd.notna(row.get(col)) else ""
                column_texts[col].append(value)

    if not valid_rows:
        raise ValueError(f"No valid entries found in strategy CSV: {filename}")

    logging.info(f"[UPLOAD SERVICE] Generating embeddings for {len(valid_rows)} rows x {len(all_columns)} columns")
    column_embeddings: dict[str, list] = {}
    for col in all_columns:
        column_embeddings[col] = generate_embeddings_batch(column_texts[col], show_progress=False)
        logging.info(f"[UPLOAD SERVICE] ✓ Embeddings for column: '{col}'")

    entries = []
    for i in range(len(valid_rows)):
        entry: dict = {}
        for col in all_columns:
            safe_col = col.replace(' ', '_').replace('-', '_').replace('.', '_')
            entry[safe_col] = column_texts[col][i]
            entry[f"{safe_col}_embedding"] = column_embeddings[col][i] if column_texts[col][i] else None
        entries.append(entry)

    payload_bytes = json.dumps({"data": entries}).encode('utf-8')
    gzip_bytes = gzip.compress(payload_bytes)
    logging.info(
        f"[UPLOAD SERVICE] ✓ Compressed embeddings payload: "
        f"{len(payload_bytes)/(1024*1024):.2f} MB → {len(gzip_bytes)/(1024*1024):.2f} MB "
        f"({len(entries)} entries)"
    )
    return gzip_bytes, len(entries)


def extract_and_store_standards_text(
    file_bytes: bytes,
    filename: str,
    user_id: int,
    blob_url: str | None = None
) -> dict:
    """
    Extract text from standards file and store in MongoDB.

    IMPLEMENTATION with Pydantic models & repository:
    1. Extracts full text from file bytes.
    2. Runs proactive LLM specifications extraction.
    3. Validates structured specifications using TechnicalSpecifications model.
    4. Upserts hydrated StandardDocument using StandardsRepository.
    """
    from datetime import UTC, datetime
    import re

    from common.infra.repositories.standards_repository import StandardsRepository
    from common.models.standards import StandardDocument, TechnicalSpecifications
    from common.services.file_extractor import extract_text_from_file

    try:
        logging.info(f"[STANDARDS_UPLOAD] Extracting text from: {filename} ({len(file_bytes)} bytes)")

        extraction_result = extract_text_from_file(file_bytes, filename)
        if not extraction_result['success']:
            logging.error(f"[STANDARDS_UPLOAD] Text extraction failed: {extraction_result.get('error')}")
            return {
                "success": False,
                "error": f"Extraction failed: {extraction_result.get('error')}"
            }

        extracted_text = extraction_result['extracted_text']
        logging.info(f"[STANDARDS_UPLOAD] Extracted {len(extracted_text)} characters from {filename}")

        technical_specifications = None
        technical_specifications_error = None

        logging.info(f"[STANDARDS_UPLOAD] Extracting technical specifications from {filename}")
        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate

            from common.ai.llm.manager import get_flash_llm
            from common.ai.prompts.templates import STANDARDS_RAG_PROMPT

            llm = get_flash_llm()
            prompt = ChatPromptTemplate.from_template(STANDARDS_RAG_PROMPT)
            chain = prompt | llm | StrOutputParser()

            # Dynamic chunk size based on PDF file size in bytes (file_bytes)
            pdf_size = len(file_bytes)
            if pdf_size < 1 * 1024 * 1024:      # < 1 MB
                chunk_size = 20000
            elif pdf_size < 5 * 1024 * 1024:    # 1 - 5 MB
                chunk_size = 50000
            elif pdf_size < 15 * 1024 * 1024:   # 5 - 15 MB
                chunk_size = 100000
            else:                               # >= 15 MB
                chunk_size = 200000

            text_len = len(extracted_text)
            chunks = []
            for i in range(0, text_len, chunk_size):
                chunks.append(extracted_text[i:i + chunk_size])

            logging.info(f"[STANDARDS_UPLOAD] File size: {pdf_size} bytes. Chunk size: {chunk_size}. Extracted text length: {text_len}. Processing in {len(chunks)} chunks.")

            all_specs = []
            for idx, chunk in enumerate(chunks):
                if idx > 0:
                    import time
                    time.sleep(2.0)

                logging.info(f"[STANDARDS_UPLOAD] Processing chunk {idx+1}/{len(chunks)} ({len(chunk)} characters)")
                context_text = f"--- SOURCE: {filename} (Chunk {idx+1}/{len(chunks)}) ---\n{chunk}\n"
                
                try:
                    llm_response = chain.invoke({
                        "category": f"All Instruments and Technical Specifications from {filename}",
                        "standards_text": context_text
                    })

                    cleaned_response = llm_response.strip()
                    cleaned_response = re.sub(r'^```[a-zA-Z]*\s*', '', cleaned_response)
                    cleaned_response = re.sub(r'\s*```\s*$', '', cleaned_response)
                    cleaned_response = cleaned_response.strip()
                    if not cleaned_response.startswith('{'):
                        match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
                        if match:
                            cleaned_response = match.group(0)

                    specs = json.loads(cleaned_response)
                    spec_data = specs.get('specifications', specs)
                    if spec_data and isinstance(spec_data, dict):
                        all_specs.append(spec_data)
                except Exception as chunk_err:
                    logging.error(f"[STANDARDS_UPLOAD] Failed to extract specifications from chunk {idx+1}: {chunk_err}")

            if not all_specs:
                raise ValueError("No specifications extracted from any chunk")

            # Merge specs key-by-key
            merged_specs = {}
            for spec in all_specs:
                for k, v in spec.items():
                    if v is None or str(v).strip() == "":
                        continue
                    v_str = str(v).strip()
                    if k not in merged_specs:
                        merged_specs[k] = v_str
                    else:
                        existing = str(merged_specs[k]).strip()
                        if v_str.lower() not in existing.lower() and existing.lower() not in v_str.lower():
                            merged_specs[k] = f"{existing}, {v_str}"
                        elif len(v_str) > len(existing):
                            merged_specs[k] = v_str

            # Schema validate and type specifications using Pydantic
            technical_specifications = TechnicalSpecifications.model_validate(merged_specs)
            logging.info(f"[STANDARDS_UPLOAD] Successfully extracted and validated specifications for {filename} from {len(chunks)} chunks")
        except Exception as e:
            technical_specifications_error = str(e)
            logging.error(f"[STANDARDS_UPLOAD] LLM extraction failed for {filename}: {e}", exc_info=True)

        # Get existing catalog to check for old blob cleanup
        catalog = StandardsRepository.get_catalog_for_user(user_id)
        existing = next((d for d in catalog.documents if d.filename == filename), None)
        old_blob_url = existing.blob_url if existing else None

        # Build hydrated StandardDocument
        doc = StandardDocument(
            user_id=user_id,
            filename=filename,
            file_type=extraction_result['file_type'],
            full_text=extracted_text,
            technical_specifications=technical_specifications,
            technical_specifications_error=technical_specifications_error,
            character_count=extraction_result['character_count'],
            uploaded_at=datetime.now(UTC).isoformat(),
            blob_url=blob_url
        )

        # Idempotently save using repository
        save_ok = StandardsRepository.save_document(doc)
        
        # Load the updated document ID if saved successfully
        if save_ok:
            updated_catalog = StandardsRepository.get_catalog_for_user(user_id)
            updated_doc = next((d for d in updated_catalog.documents if d.filename == filename), None)
            doc_id = updated_doc.id if updated_doc else "Unknown"
        else:
            doc_id = "Unknown"

        if old_blob_url and blob_url and old_blob_url != blob_url:
            try:
                from common.infra.azure_blob import azure_blob_manager

                azure_blob_manager.delete_document_from_url(old_blob_url)
                logging.info(f"[STANDARDS_UPLOAD] Deleted superseded blob for {filename}")
            except Exception as cleanup_error:
                logging.warning(f"[STANDARDS_UPLOAD] Failed to delete old blob for {filename}: {cleanup_error}")

        return {
            "success": save_ok,
            "document_id": doc_id,
            "filename": filename,
            "is_update": existing is not None,
            "blob_url": blob_url,
            "llm_extraction_succeeded": technical_specifications_error is None,
            "llm_extraction_error": technical_specifications_error,
        }

    except Exception as e:
        logging.error(f"[STANDARDS_UPLOAD] Error processing file {filename}: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


def _queue_llm_task(payload: dict) -> bool:
    """Push a task into the Redis queue used by the background worker."""
    try:
        import redis as _redis
        redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_CONNECTION_STRING", "redis://localhost:6379")
        client = _redis.from_url(redis_url)
        client.lpush("llm-tasks", json.dumps(payload))
        return True
    except Exception as e:
        logging.error(f"[UPLOAD SERVICE] Failed to queue task: {e}", exc_info=True)
        return False


def process_standards_blob_for_rag(user_id: str | int, filename: str, blob_url: str) -> dict:
    """
    Download a standards document from blob storage and persist its extracted content.
    This is the durable worker-side path used by the Azure queue trigger.
    """
    from common.infra.azure_blob import azure_blob_manager

    logging.info(f"[UPLOAD SERVICE] Processing queued standards document: {filename} for user {user_id}")
    file_bytes = azure_blob_manager.download_document_from_url(blob_url)
    result = extract_and_store_standards_text(file_bytes, filename, int(user_id), blob_url)

    if not result.get("success"):
        raise RuntimeError(result.get("error") or f"Failed to process standards document {filename}")

    return result


def upload_and_queue_standards_processing(
    file_bytes: bytes,
    filename: str,
    user_id: str | int,
    content_type: str,
) -> dict:
    """
    Upload a standards document to Azure Blob and schedule durable processing.
    Falls back to inline extraction if queue submission is unavailable.
    """
    from common.infra.azure_blob import azure_blob_manager

    logging.info(f"[UPLOAD SERVICE] Uploading standards document: {filename} for user {user_id}")
    blob_info = azure_blob_manager.upload_standards_document(
        file_bytes=file_bytes,
        filename=filename,
        user_id=int(user_id),
        content_type=content_type,
    )

    blob_url = blob_info.get("blobUrl") if blob_info else None
    if not blob_url:
        return {
            "success": False,
            "error": f"Blob URL missing for standards document: {filename}",
        }

    if _queue_llm_task({
        "type": "standards_upload",
        "user_id": user_id,
        "filename": filename,
        "blob_url": blob_url
    }):
        logging.info(f"[UPLOAD SERVICE] Queued standards processing for {filename}")
        return {
            "success": True,
            "queued": True,
            "processed_inline": False,
            "blob_url": blob_url,
        }

    logging.info(f"[UPLOAD SERVICE] Processing standards inline for {filename} (Queue unavailable)")
    result = extract_and_store_standards_text(file_bytes, filename, int(user_id), blob_url)
    result.update({
        "queued": False,
        "processed_inline": True,
        "blob_url": blob_url,
    })
    return result


def process_standards_upload(file_bytes: bytes, safe_filename: str, user_id: str | int, safe_content_type: str) -> None:
    """
    Legacy entry point retained for compatibility. It now uses the same durable queue path.
    """
    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            result = upload_and_queue_standards_processing(
                file_bytes=file_bytes,
                filename=safe_filename,
                user_id=user_id,
                content_type=safe_content_type,
            )
            if result.get("success"):
                return

            raise RuntimeError(result.get("error") or "Unknown standards upload failure")
        except Exception as e:
            logging.error(f"[UPLOAD SERVICE] Standards processing error for {safe_filename} (attempt {attempt + 1}/{max_retries}): {e}")

            if attempt < max_retries - 1:
                logging.info(f"[UPLOAD SERVICE] Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logging.error(f"[UPLOAD SERVICE] All retry attempts failed for {safe_filename}: {e}", exc_info=True)
                try:
                    from common.notification_manager import create_failure_notification

                    create_failure_notification(
                        user_id=user_id,
                        username='Unknown',
                        user_email='',
                        failed_step='Standards Upload',
                        error_message=f'Failed to upload standards document after {max_retries} attempts: {str(e)}',
                        page='upload',
                        additional_context={'filename': safe_filename}
                    )
                except Exception as notify_err:
                    logging.warning(f"[UPLOAD SERVICE] Failed to send failure notification: {notify_err}")
                return


def extract_assets_from_csv(file_bytes: bytes, filename: str) -> list[dict]:
    """
    Parse CSV assets file into a list of asset dicts (no embeddings — RAG reads the actual file on-demand).
    """
    from io import BytesIO

    import pandas as pd

    logging.info(f"[UPLOAD SERVICE] Parsing assets CSV: {filename}")
    df = pd.read_csv(BytesIO(file_bytes))
    df.columns = df.columns.str.strip().str.lower()

    column_mapping = {
        'asset': 'asset_name', 'name': 'asset_name', 'equipment_name': 'asset_name',
        'equipment': 'asset_name', 'type': 'asset_type', 'equipment_type': 'asset_type',
        'category': 'asset_type', 'vendor': 'manufacturer', 'supplier': 'manufacturer',
        'make': 'manufacturer', 'site': 'location', 'plant': 'location',
        'facility': 'location', 'model_number': 'model', 'serial': 'serial_number',
        'sn': 'serial_number', 'tag': 'tag_number', 'tag_no': 'tag_number',
        'tag_id': 'tag_number', 'tag number': 'tag_number', 'tag_num': 'tag_number',
        'tag no': 'tag_number', 'tag no.': 'tag_number', 'instrument_tag': 'tag_number',
        'instrument tag': 'tag_number', 'loop_tag': 'tag_number', 'loop tag': 'tag_number',
    }
    df.rename(columns=column_mapping, inplace=True)

    entries = df.to_dict('records')
    for entry in entries:
        for key in list(entry.keys()):
            if pd.isna(entry[key]) or entry[key] is None:
                entry[key] = ''
            else:
                entry[key] = str(entry[key]).strip()

    logging.info(f"[UPLOAD SERVICE] ✓ Parsed {len(entries)} asset entries from CSV")
    return entries


def process_strategy_upload(file_bytes: bytes, safe_filename: str, user_id: str | int) -> None:
    """
    Full strategy upload: parse CSV → generate embeddings → upload to blob → store in MongoDB.
    Called synchronously from auth/routes.py during signup flow.
    """
    from datetime import UTC, datetime
    from io import BytesIO

    import pandas as pd

    from common.infra.azure_blob import azure_blob_manager
    from common.infra.repositories.strategy_repository import StrategyRepository
    from common.models.strategy import StrategyDocument, StandardStorage

    try:
        logging.info(f"[UPLOAD SERVICE] Processing strategy document: {safe_filename} for user: {user_id}")

        gzip_bytes, entry_count = extract_strategy_embeddings_from_csv(file_bytes, safe_filename)

        blob_info = azure_blob_manager.upload_strategy_document(file_bytes, safe_filename, int(user_id), 'text/csv')
        embeddings_blob_url = azure_blob_manager.upload_strategy_embeddings(gzip_bytes, safe_filename, int(user_id))
        blob_info['embeddingsBlobUrl'] = embeddings_blob_url

        df = pd.read_csv(BytesIO(file_bytes))
        csv_columns = list(df.columns.str.strip().str.lower())

        # Construct using Pydantic models
        storage_model = StandardStorage.model_validate(blob_info)
        doc = StrategyDocument(
            user_id=int(user_id),
            filename=safe_filename,
            uploaded_at=datetime.now(UTC).isoformat(),
            entry_count=entry_count,
            extraction_method="upload_time_embeddings",
            csv_columns=csv_columns,
            storage=storage_model,
            status="ready"
        )

        # Save via StrategyRepository
        success = StrategyRepository.save_document(doc)
        if success:
            logging.info(f"[UPLOAD SERVICE] ✓ Strategy upload complete: {entry_count} entries, {safe_filename}")
        else:
            logging.error(f"[UPLOAD SERVICE] Strategy upload failed to save document to repository for {safe_filename}")

    except Exception as e:
        logging.error(f"[UPLOAD SERVICE] Strategy upload error for {safe_filename}: {e}", exc_info=True)


def process_assets_upload(file_bytes: bytes, safe_filename: str, user_id: str | int) -> None:
    """
    Full assets upload: parse CSV → upload to blob → store in MongoDB.
    Called synchronously from auth/routes.py during signup flow.
    """
    from datetime import UTC, datetime

    from common.infra.azure_blob import azure_blob_manager
    from common.infra.mongodb_config import get_mongodb_connection

    try:
        logging.info(f"[UPLOAD SERVICE] Processing assets document: {safe_filename} for user: {user_id}")

        entries = extract_assets_from_csv(file_bytes, safe_filename)
        if not entries:
            logging.warning(f"[UPLOAD SERVICE] No entries found in assets CSV: {safe_filename}")
            return

        blob_info = azure_blob_manager.upload_assets_document(file_bytes, safe_filename, int(user_id), 'text/csv')

        conn = get_mongodb_connection()
        conn['collections']['assets'].update_one(
            {"user_id": user_id, "filename": safe_filename},
            {"$set": {
                "uploaded_at": datetime.now(UTC).isoformat(),
                "entry_count": len(entries),
                "extraction_method": "csv_direct_parse",
                "storage": blob_info,
            }},
            upsert=True,
        )
        logging.info(f"[UPLOAD SERVICE] ✓ Assets upload complete: {len(entries)} entries, {safe_filename}")
    except Exception as e:
        logging.error(f"[UPLOAD SERVICE] Assets upload error for {safe_filename}: {e}", exc_info=True)


def process_strategy_blob_for_rag(user_id: str | int, filename: str, blob_url: str) -> None:
    """
    Download a strategy document from blob storage, extract embeddings, save back, and update Mongo.
    This is the durable worker-side path used by the Azure queue trigger.
    """
    from common.infra.azure_blob import azure_blob_manager
    from datetime import UTC, datetime
    from io import BytesIO
    import pandas as pd
    from common.infra.repositories.strategy_repository import StrategyRepository
    from common.models.strategy import StrategyDocument, StandardStorage

    logging.info(f"[UPLOAD SERVICE] Processing queued strategy document: {filename} for user {user_id}")
    file_bytes = azure_blob_manager.download_document_from_url(blob_url)
    try:
        gzip_bytes, entry_count = extract_strategy_embeddings_from_csv(file_bytes, filename)
        
        # Original blob is already present, we just upload the newly generated embeddings blob
        embeddings_blob_url = azure_blob_manager.upload_strategy_embeddings(gzip_bytes, filename, int(user_id))
        
        # Assemble storage info matching what was sent earlier for continuity
        blob_info = {
            "storage": "azure_blob",
            "blobUrl": blob_url,
            "embeddingsBlobUrl": embeddings_blob_url,
            "container": "strategy-documents",
            "blobName": f"user_{user_id}/files/{filename}"
        }

        df = pd.read_csv(BytesIO(file_bytes))
        csv_columns = list(df.columns.str.strip().str.lower())

        # Construct using Pydantic models
        storage_model = StandardStorage.model_validate(blob_info)
        doc = StrategyDocument(
            user_id=int(user_id),
            filename=filename,
            uploaded_at=datetime.now(UTC).isoformat(),
            entry_count=entry_count,
            extraction_method="upload_time_embeddings",
            csv_columns=csv_columns,
            storage=storage_model,
            status="ready"
        )

        # Save via StrategyRepository
        success = StrategyRepository.save_document(doc)
        if success:
            logging.info(f"[UPLOAD SERVICE] ✓ Strategy queued processing complete: {entry_count} entries, {filename}")
        else:
            logging.error(f"[UPLOAD SERVICE] Strategy queued processing failed to save document to repository for {filename}")

    except Exception as e:
        logging.error(f"[UPLOAD SERVICE] Strategy queued processing error for {filename}: {e}", exc_info=True)
        # Update repository to show error state
        try:
            catalog = StrategyRepository.get_catalog_for_user(user_id)
            matching_doc = next((d for d in catalog.documents if d.filename == filename), None)
            if matching_doc and matching_doc.id:
                StrategyRepository.update_metadata(matching_doc.id, {
                    "status": "error",
                    "error_message": str(e)
                })
            else:
                from common.infra.mongodb_config import get_mongodb_connection
                conn = get_mongodb_connection()
                conn['collections']['stratergy'].update_one(
                    {"user_id": user_id, "filename": filename},
                    {"$set": {
                        "status": "error",
                        "error_message": str(e)
                    }}
                )
        except Exception as db_err:
            logging.error(f"[UPLOAD SERVICE] Failed to update error status for {filename}: {db_err}")

def process_assets_blob_for_rag(user_id: str | int, filename: str, blob_url: str) -> None:
    """
    Download an assets document from blob storage, parse, and update Mongo.
    This is the durable worker-side path used by the Azure queue trigger.
    """
    from common.infra.azure_blob import azure_blob_manager
    from datetime import UTC, datetime
    from common.infra.mongodb_config import get_mongodb_connection

    logging.info(f"[UPLOAD SERVICE] Processing queued assets document: {filename} for user {user_id}")
    file_bytes = azure_blob_manager.download_document_from_url(blob_url)
    try:
        entries = extract_assets_from_csv(file_bytes, filename)
        
        blob_info = {
            "storage": "azure_blob",
            "blobUrl": blob_url,
            "container": "assets-documents",
            "blobName": f"user_{user_id}/{filename}"
        }

        conn = get_mongodb_connection()
        conn['collections']['assets'].update_one(
            {"user_id": user_id, "filename": filename},
            {"$set": {
                "uploaded_at": datetime.now(UTC).isoformat(),
                "entry_count": len(entries) if entries else 0,
                "extraction_method": "csv_direct_parse",
                "storage": blob_info,
                "status": "ready"
            }},
            upsert=True,
        )
        logging.info(f"[UPLOAD SERVICE] ✓ Assets queued processing complete: {len(entries) if entries else 0} entries, {filename}")
    except Exception as e:
        logging.error(f"[UPLOAD SERVICE] Assets queued processing error for {filename}: {e}", exc_info=True)
        conn = get_mongodb_connection()
        conn['collections']['assets'].update_one(
            {"user_id": user_id, "filename": filename},
            {"$set": {
                "status": "error",
                "error_message": str(e)
            }}
        )
