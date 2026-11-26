from common.helpers.azure_session import get_session
"""Assets domain routes."""
import logging
import os
from datetime import datetime, UTC, timedelta
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.core.security import validate_uploaded_file
from app.core.errors import notify_failure
from app.models.db.base import db
from app.models.db.user_model import User

from common.helpers.responses import JSONResponse

blueprint = APIRouter()


@blueprint.get("/api/debug/criticality")
@login_required
async def debug_criticality(request: Request):
    session = get_session(request)
    try:
        from common.infra.blob_sas import generate_sas_url
        from common.infra.mongodb_config import get_mongodb_connection
        from common.ai.rag.assets_rag import _extract_csv_assets_from_sas_url

        user_id = session.get('user_id')
        conn = get_mongodb_connection()
        conn.get('database')
        assets_col = conn['collections']['assets']

        try:
            user_id_int = int(user_id)
            query = {"$or": [{"user_id": user_id}, {"user_id": user_id_int}]}
        except (ValueError, TypeError):
            query = {"user_id": user_id}

        docs = list(assets_col.find(query))
        csv_columns = []
        csv_tags = []

        for doc in docs:
            filename = doc.get('filename', '')
            if not filename.lower().endswith('.csv'):
                continue
            blob_url = doc.get('storage', {}).get('blobUrl')
            if not blob_url:
                continue
            sas_url = generate_sas_url(blob_url, expiry_hours=1)
            if not sas_url:
                continue
            data = _extract_csv_assets_from_sas_url(sas_url, filename)
            if data:
                csv_columns = list(data[0].keys())
                csv_tags = list({str(r.get('tag_number', '')).strip() for r in data if r.get('tag_number')})
            break

        logs_col = conn['collections']['instrument_logs']
        logs_count = logs_col.count_documents({})
        live_count = logs_col.count_documents({'source': 'live_simulation'})
        hist_count = logs_col.count_documents({'source': 'historical_seed'})
        sample_logs = list(logs_col.find({'source': {'$in': ['live_simulation', 'historical_seed']}}, {'tag_number': 1, 'sim_state': 1, 'source': 1, '_id': 0}).limit(5))
        log_tags = list({d['tag_number'] for d in logs_col.find({}, {'tag_number': 1, '_id': 0}).limit(500) if d.get('tag_number')})

        csv_tag_set = set(csv_tags)
        log_tag_set = set(log_tags)
        matched = list(csv_tag_set & log_tag_set)
        unmatched_csv = list(csv_tag_set - log_tag_set)[:10]

        return JSONResponse({
            'csv_columns': csv_columns,
            'csv_tag_count': len(csv_tags),
            'csv_tags_sample': sorted(csv_tags)[:10],
            'instrument_logs_total': logs_count,
            'instrument_logs_live': live_count,
            'instrument_logs_historical': hist_count,
            'instrument_logs_tags_sample': sorted(log_tags)[:10],
            'matched_tags_count': len(matched),
            'matched_tags_sample': sorted(matched)[:10],
            'unmatched_csv_tags_sample': unmatched_csv,
            'sample_log_docs': sample_logs,
        }, status_code=200)
    except Exception as e:
        import traceback
        notify_failure("Debug Criticality Processing", str(e), page="assets", user_id=session.get('user_id'))
        return JSONResponse({'error': str(e), 'trace': traceback.format_exc()}, status_code=500)


@blueprint.get("/api/assets-data")
@login_required
async def get_assets_data(request: Request):
    session = get_session(request)
    try:
        from common.infra.mongodb_config import Collections, get_mongodb_connection

        logging.info("[ASSETS_DATA] Fetching assets data")

        user_id = session.get('user_id')
        if not user_id:
            return JSONResponse({"success": False, "error": "User not authenticated"}, status_code=401)

        current_user = db.session.get(User, user_id)
        if not current_user:
            return JSONResponse({"success": False, "error": "User not found"}, status_code=404)

        conn = get_mongodb_connection()
        if not conn:
            return JSONResponse({"success": False, "error": "Database connection failed"}, status_code=500)

        assets_collection = conn['collections'][Collections.ASSETS]

        if current_user.role and current_user.role.lower() == 'admin':
            if getattr(current_user, 'company', None):
                query = {"organization": current_user.company}
            else:
                try:
                    user_id_int = int(user_id)
                    query = {"$or": [{"user_id": user_id}, {"user_id": user_id_int}]}
                except (ValueError, TypeError):
                    query = {"user_id": user_id}
        else:
            try:
                user_id_int = int(user_id)
                query = {"$or": [{"user_id": user_id}, {"user_id": user_id_int}]}
            except (ValueError, TypeError):
                query = {"user_id": user_id}

        documents = list(assets_collection.find(query))

        if not documents:
            logging.info(f"[ASSETS_DATA] No assets documents found for user {user_id}")
            return JSONResponse({"success": True, "data": [], "total_count": 0}, status_code=200)

        all_assets = []

        from common.infra.blob_sas import generate_sas_url
        from common.ai.rag.assets_rag import _extract_csv_assets_from_sas_url

        for doc in documents:
            filename = doc.get('filename', 'Unknown')
            uploaded_at = doc.get('uploaded_at', '')
            blob_url = doc.get('storage', {}).get('blobUrl')

            if not blob_url:
                logging.warning(f"[ASSETS_DATA] No blob URL found for document: {filename}")
                continue

            if not filename.lower().endswith('.csv'):
                logging.warning(f"[ASSETS_DATA] Skipping non-CSV file: {filename}")
                continue

            try:
                logging.info(f"[ASSETS_DATA] Processing CSV file: {filename}")
                cached_sas = doc.get('storage', {}).get('cachedSasUrl')
                cached_sas_expiry = doc.get('storage', {}).get('sasUrlExpiry')

                sas_url = None
                if cached_sas and cached_sas_expiry:
                    try:
                        expiry_dt = datetime.fromisoformat(cached_sas_expiry)
                        if datetime.now(UTC) < expiry_dt:
                            sas_url = cached_sas
                            logging.info(f"[ASSETS_DATA] Using cached SAS URL for: {filename}")
                    except Exception:
                        pass

                if not sas_url:
                    sas_url = generate_sas_url(blob_url, expiry_hours=24)
                    if sas_url:
                        sas_expiry = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
                        assets_collection.update_one(
                            {'_id': doc['_id']},
                            {'$set': {
                                'storage.cachedSasUrl': sas_url,
                                'storage.sasUrlExpiry': sas_expiry
                            }}
                        )
                        logging.info(f"[ASSETS_DATA] Generated new SAS URL for: {filename}")

                if not sas_url:
                    logging.error(f"[ASSETS_DATA] Failed to get SAS URL for: {filename}")
                    continue

                data_array = _extract_csv_assets_from_sas_url(sas_url, filename)

                if not data_array:
                    logging.warning(f"[ASSETS_DATA] No data extracted from CSV: {filename}")
                    continue

                logging.info(f"[ASSETS_DATA] Successfully extracted {len(data_array)} rows from: {filename}")

            except Exception as e:
                logging.error(f"[ASSETS_DATA] Failed to process CSV file {filename}: {e}")
                import traceback
                logging.error(traceback.format_exc())
                continue

            doc_id_str = str(doc['_id'])
            for entry in data_array:
                asset_with_meta = {
                    'source_file': filename,
                    'uploaded_at': uploaded_at,
                    '_doc_id': doc_id_str,
                    **entry
                }
                all_assets.append(asset_with_meta)

        for row in all_assets:
            score = 100.0
            existing_et = row.get('error_types', row.get('error_type', ''))
            if isinstance(existing_et, str):
                error_types = [e.strip() for e in existing_et.split(',') if e.strip()]
            elif isinstance(existing_et, list):
                error_types = list(existing_et)
            else:
                error_types = []

            csv_error_prone = str(row.get('is_error_prone', '')).strip().lower() in ['true', 'yes', '1', 'y']
            cond = str(row.get('asset_condition', '')).strip().lower()
            status = str(row.get('status', '')).strip().lower()
            crit = str(row.get('criticality', '')).strip().lower()

            if cond in ['poor', 'critical', 'failed', 'bad', 'end of life']:
                score = min(score, 30.0)
                if 'Poor Condition' not in error_types:
                    error_types.append('Poor Condition')
            elif cond in ['fair', 'degraded', 'needs maintenance']:
                score = min(score, 65.0)
                if 'Degraded Condition' not in error_types:
                    error_types.append('Degraded Condition')

            if status in ['offline', 'failed', 'out of service', 'critical']:
                score = min(score, 30.0)
                if 'Status Offline/Failed' not in error_types:
                    error_types.append('Status Offline/Failed')
            elif status in ['maintenance', 'warning', 'standby']:
                score = min(score, 65.0)
                if 'Status Warning/Maintenance' not in error_types:
                    error_types.append('Status Warning/Maintenance')

            if crit in ['high', 'extreme', 'critical'] and score <= 65.0:
                score = min(score, 45.0)
                if 'High Criticality Issue' not in error_types:
                    error_types.append('High Criticality Issue')

            if score == 100.0 and len(error_types) > 0:
                score = 45.0

            if score >= 80:
                health_status = 'healthy'
            elif score >= 50:
                health_status = 'warning'
            else:
                health_status = 'critical'

            row['_health_status'] = health_status
            row['_health_score'] = score
            row['_procurement_flagged'] = health_status == 'critical'
            row['is_error_prone'] = csv_error_prone or (health_status in ('critical', 'warning'))
            row['error_types'] = error_types

        logging.info(f"[ASSETS_DATA] Returning {len(all_assets)} assets from {len(documents)} documents")

        return JSONResponse({
            "success": True,
            "data": all_assets,
            "total_count": len(all_assets),
            "document_count": len(documents)
        }, status_code=200, headers={'Cache-Control': 'private, max-age=30'})

    except Exception as e:
        logging.exception(f"[ASSETS_DATA] Error fetching assets data: {e}")
        notify_failure("Assets Data Fetch", str(e), page="assets", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
