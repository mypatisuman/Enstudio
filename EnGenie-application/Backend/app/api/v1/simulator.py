from common.helpers.azure_session import get_session
"""
Simulator domain routes.
"""
import logging
import os
from datetime import datetime
from fastapi import APIRouter, Request

from app.core.security import login_required
from app.core.errors import notify_failure

from common.helpers.responses import JSONResponse

blueprint = APIRouter()


@blueprint.post("/api/ingest/readings")
async def ingest_readings(request: Request):
    session = get_session(request)

    user_id = session.get('user_id')

    if not user_id:
        provided_key = request.headers.get('X-Ingest-Key', '')
        ingest_key = os.environ.get('INGEST_API_KEY', '')
        if not ingest_key or provided_key != ingest_key:
            return JSONResponse(
                {'success': False, 'error': 'Unauthorized — provide a valid X-Ingest-Key or an active session'},
                status_code=401,
            )
        user_id = request.headers.get('X-User-Id', 'external_system')

    try:
        body = await request.json()
    except Exception:
        body = None
    if not body:
        return JSONResponse({'success': False, 'error': 'Request body must be JSON'}, status_code=400)

    readings = body.get('readings')
    if not readings or not isinstance(readings, list):
        return JSONResponse({'success': False, 'error': '"readings" array is required'}, status_code=400)

    if len(readings) > 10_000:
        return JSONResponse({'success': False, 'error': 'Maximum 10 000 readings per request'}, status_code=400)

    asset_id = body.get('asset_id')
    source = body.get('source', 'external_api')

    try:
        from common.ai.rag.assets_rag import ingest_instrument_logs
        result = ingest_instrument_logs(
            user_id=str(user_id),
            logs_data=readings,
            asset_id=asset_id,
            source_file=source,
            generate_embeddings=False,
        )
        logging.info(f"[INGEST] user={user_id} source={source} readings={len(readings)}")
        return JSONResponse(result)
    except Exception as e:
        logging.exception(f"[INGEST] Failed to ingest readings: {e}")
        notify_failure("Ingest Readings Processing", str(e), page="simulator", user_id=user_id)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@blueprint.get("/api/simulator/readings")
@login_required
async def get_simulator_readings(request: Request):
    session = get_session(request)

    try:
        from common.infra.mongodb_config import get_mongodb_connection

        user_id = session.get('user_id')
        conn = get_mongodb_connection()
        db = conn.get('database')
        if db is None:
            return JSONResponse({'success': False, 'error': 'DB unavailable'}, status_code=500)

        try:
            uid_int = int(user_id)
            base_match: dict = {'$or': [{'user_id': user_id}, {'user_id': uid_int}]}
        except (ValueError, TypeError):
            base_match = {'user_id': user_id}

        source_param = request.query_params.get('source', 'live_simulation')
        allowed_sources = {'live_simulation', 'historical_seed', 'external_api'}
        base_match['source'] = source_param if source_param in allowed_sources else 'live_simulation'

        tag = request.query_params.get('tag_number', '').strip()
        if tag:
            base_match['tag_number'] = tag

        sim_state_param = request.query_params.get('sim_state', '').strip().lower()
        if sim_state_param in {'healthy', 'degrading', 'critical', 'anomalous'}:
            base_match['sim_state'] = sim_state_param

        error_only = request.query_params.get('error_only', '').lower() in ('1', 'true')
        if error_only:
            base_match['$or'] = [
                {'severity': 'critical'},
                {'sim_state': {'$in': ['critical', 'anomalous']}},
            ]

        since_str = request.query_params.get('since', '').strip()
        if since_str:
            try:
                since_dt = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
                base_match['timestamp'] = {'$gte': since_dt}
            except ValueError:
                pass

        try:
            limit = min(int(request.query_params.get('limit', 500)), 5000)
        except ValueError:
            limit = 500

        projection = {
            '_id': 0, 'tag_number': 1, 'asset_id': 1, 'asset_type': 1,
            'value': 1, 'timestamp': 1, 'severity': 1, 'sim_state': 1,
            'source': 1, 'message': 1, 'log_type': 1,
        }

        readings = list(
            db['instrument_logs'].find(base_match, projection).sort('timestamp', -1).limit(limit)
        )

        error_count = 0
        for r in readings:
            if isinstance(r.get('timestamp'), datetime):
                r['timestamp'] = r['timestamp'].isoformat()
            if hasattr(r.get('asset_id'), '__str__'):
                r['asset_id'] = str(r['asset_id'])
            is_error = r.get('severity') == 'critical' or r.get('sim_state') in ('critical', 'anomalous')
            r['is_error_prone'] = is_error
            if is_error:
                error_count += 1

        logging.info(f"[SIMULATOR_READINGS] user={user_id} source={source_param} returned={len(readings)} errors={error_count}")

        return JSONResponse({
            'success': True,
            'count': len(readings),
            'error_count': error_count,
            'readings': readings,
        })

    except Exception as e:
        logging.exception(f"[SIMULATOR_READINGS] {e}")
        notify_failure("Simulator Readings Fetch", str(e), page="simulator", user_id=session.get('user_id'))
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)
