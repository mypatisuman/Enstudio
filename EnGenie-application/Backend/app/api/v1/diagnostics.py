from common.helpers.azure_session import get_session
"""Diagnostics domain routes."""
import logging
import os
from datetime import datetime, UTC
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.core.errors import notify_failure
from app.models.db.base import db

from common.helpers.responses import JSONResponse

blueprint = APIRouter()


@blueprint.get("/api/assets/{asset_id}/diagnostics")
@login_required
async def get_asset_diagnostics(request: Request, asset_id: str):
    session = get_session(request)
    try:
        from common.infra.mongodb_config import get_mongodb_connection
        conn = get_mongodb_connection()
        db_inst = conn.get('database')
        if db_inst is None:
            return JSONResponse({'success': False, 'error': 'DB unavailable'}, status_code=500)

        sessions = list(db_inst['diagnostic_sessions'].find({'asset_id': asset_id}, {'_id': 0}).sort('created_at', -1).limit(5))
        anomalies = list(db_inst['anomaly_results'].find({'tag_number': asset_id}, {'_id': 0}).sort('detected_at', -1).limit(10))

        for r in anomalies:
            for field in ('detected_at', 'timestamp'):
                if isinstance(r.get(field), datetime):
                    r[field] = r[field].isoformat()

        from bson.objectid import ObjectId
        asset = db_inst['assets'].find_one({"_id": ObjectId(asset_id)}) if len(str(asset_id)) == 24 else None

        base_score = 100.0
        factors = []

        if asset:
            crit = str(asset.get('criticality', '')).strip().lower()
            status = str(asset.get('asset_condition', '')).strip().lower()
            err_types_raw = ''
        else:
            crit = request.query_params.get('criticality', '').strip().lower()
            status = request.query_params.get('condition', '').strip().lower()
            err_types_raw = request.query_params.get('error_types', '').strip()

        if err_types_raw:
            for e in err_types_raw.split(','):
                e = e.strip()
                if e and e not in factors:
                    factors.append(e)

        if status in ['poor', 'failed', 'faulty']:
            if 'Poor Condition' not in factors:
                factors.append('Poor Condition')
        elif status in ['maintenance', 'warning', 'standby', 'degraded']:
            if 'Status Warning/Maintenance' not in factors:
                factors.append('Status Warning/Maintenance')

        if crit in ['high', 'extreme', 'critical'] and ('Status Warning/Maintenance' in factors or 'Degraded Condition' in factors):
            if 'High Criticality Issue' not in factors:
                factors.append('High Criticality Issue')

        if any(f in factors for f in ['Poor Condition', 'Status Offline/Failed']):
            base_score = min(base_score, 30.0)
        elif any(f in factors for f in ['Degraded Condition', 'Status Warning/Maintenance']):
            base_score = min(base_score, 65.0)

        if 'High Criticality Issue' in factors:
            base_score = min(base_score, 45.0)

        if base_score == 100.0 and len(factors) > 0:
            base_score = min(base_score, 45.0)

        health = {
            "health_score": base_score,
            "health_status": "critical" if base_score < 50 else "warning" if base_score < 80 else "healthy",
            "trend_direction": "stable",
            "active_anomalies": len([a for a in anomalies if a.get('severity') in ('warning', 'critical')]),
            "factors": factors
        }

        if anomalies:
            worst_severity = next((a.get('severity') for a in anomalies if a.get('severity') == 'critical'), None)
            if not worst_severity:
                worst_severity = next((a.get('severity') for a in anomalies if a.get('severity') == 'warning'), 'healthy')
            if worst_severity == 'critical':
                health["health_score"] = max(0, health["health_score"] - len(anomalies) * 10)
                health["health_status"] = 'critical'
            elif worst_severity == 'warning':
                health["health_score"] = max(0, health["health_score"] - len(anomalies) * 5)
                if health["health_status"] == 'healthy':
                    health["health_status"] = 'warning'
            if "Recent anomaly events" not in health["factors"]:
                health["factors"].append("Recent anomaly events")

        result_payload = {
            "success": True,
            "asset_id": asset_id,
            "health": health,
            "sessions": sessions,
            "anomaly_detection": {
                "anomalies": anomalies,
                "anomalies_detected": len(anomalies),
                "total_analyzed": len(anomalies)
            }
        }
        return JSONResponse(result_payload, status_code=200)
    except Exception as e:
        logging.exception(f"[GET_ASSET_DIAGNOSTICS] {e}")
        notify_failure("Asset Diagnostics Fetch", str(e), page="diagnostics", user_id=session.get('user_id'))
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@blueprint.post("/api/diagnostics/analyze")
@login_required
async def run_diagnostics_analyze(request: Request):
    session = get_session(request)
    try:
        user_id = session.get('user_id')
        try:
            body = await request.json()
        except Exception:
            body = {}
        asset_id = body.get('asset_id')

        if not asset_id:
            return JSONResponse({'success': False, 'error': 'asset_id is required'}, status_code=400)

        from common.infra.mongodb_config import get_mongodb_connection
        conn = get_mongodb_connection()
        db_inst = conn.get('database')
        if db_inst is None:
            return JSONResponse({'success': False, 'error': 'DB unavailable'}, status_code=500)

        try:
            _uid_norm = int(user_id)
        except (ValueError, TypeError):
            _uid_norm = user_id
        raw_logs = list(db_inst['instrument_logs'].find(
            {'user_id': _uid_norm, 'tag_number': asset_id}, {'_id': 0}
        ).sort('timestamp', 1).limit(5000))

        from common.services.anomaly_detector import detect_anomalies_batch

        anomalies = []
        total_analyzed = len(raw_logs)
        anomaly_rate = 0.0

        if raw_logs:
            entries = []
            for doc in raw_logs:
                ts = doc.get("timestamp")
                entries.append({
                    "tag_number": doc.get("tag_number", asset_id),
                    "value": doc.get("value"),
                    "timestamp": ts.isoformat() if isinstance(ts, datetime) else ts,
                })

            anomaly_result = detect_anomalies_batch(entries)
            anomalies = anomaly_result.get('anomalies', [])
            total_analyzed = anomaly_result.get('total_logs', total_analyzed)
            anomaly_rate = anomaly_result.get('anomaly_rate', 0.0)

            anomalies = [
                {
                    "tag_number": a.get("tag_number", asset_id),
                    "severity": "critical" if a.get("anomaly_score", 0) > 0.8 else "warning",
                    "detected_at": datetime.now(UTC).isoformat(),
                    "timestamp": a.get("timestamp"),
                    "anomaly_score": a.get("anomaly_score"),
                    "anomaly_type": a.get("anomaly_type"),
                    "details": a.get("details", {})
                } for a in anomalies if a.get("is_anomaly")
            ]

            if anomalies:
                try:
                    db_inst['anomaly_results'].insert_many(anomalies)
                except Exception as e:
                    logging.warning(f"Failed to persist on-demand anomalies: {e}")

            anomalies.reverse()
            anomalies = anomalies[:20]

        from bson.objectid import ObjectId
        asset = db_inst['assets'].find_one({"_id": ObjectId(asset_id)}) if len(str(asset_id)) == 24 else None

        base_score = 100.0
        factors = []

        if asset:
            crit = str(asset.get('criticality', '')).strip().lower()
            status = str(asset.get('asset_condition', '')).strip().lower()
            err_types_raw = ''
        else:
            crit = str(body.get('criticality', '')).strip().lower()
            status = str(body.get('condition', '')).strip().lower()
            err_types_raw = str(body.get('error_types', '')).strip()

        if err_types_raw:
            for e in err_types_raw.split(','):
                e = e.strip()
                if e and e not in factors:
                    factors.append(e)

        if status in ['poor', 'failed', 'faulty']:
            if 'Poor Condition' not in factors:
                factors.append('Poor Condition')
        elif status in ['maintenance', 'warning', 'standby', 'degraded']:
            if 'Status Warning/Maintenance' not in factors:
                factors.append('Status Warning/Maintenance')

        if crit in ['high', 'extreme', 'critical'] and ('Status Warning/Maintenance' in factors or 'Degraded Condition' in factors):
            if 'High Criticality Issue' not in factors:
                factors.append('High Criticality Issue')

        if any(f in factors for f in ['Poor Condition', 'Status Offline/Failed']):
            base_score = min(base_score, 30.0)
        elif any(f in factors for f in ['Degraded Condition', 'Status Warning/Maintenance']):
            base_score = min(base_score, 65.0)

        if 'High Criticality Issue' in factors:
            base_score = min(base_score, 45.0)

        if base_score == 100.0 and len(factors) > 0:
            base_score = min(base_score, 45.0)

        health = {
            "health_score": base_score,
            "health_status": "critical" if base_score < 50 else "warning" if base_score < 80 else "healthy",
            "trend_direction": "stable",
            "active_anomalies": len([a for a in anomalies if a.get('severity') in ('warning', 'critical')]),
            "factors": factors
        }

        worst_severity = next((a.get('severity') for a in anomalies if a.get('severity') == 'critical'), None)
        if not worst_severity:
            worst_severity = next((a.get('severity') for a in anomalies if a.get('severity') == 'warning'), 'healthy')

        if worst_severity == 'critical':
            health["health_score"] = max(0, health["health_score"] - len(anomalies) * 10)
            health["health_status"] = 'critical'
        elif worst_severity == 'warning':
            health["health_score"] = max(0, health["health_score"] - len(anomalies) * 5)
            if health["health_status"] == 'healthy':
                health["health_status"] = 'warning'

        if anomalies and "Recent anomaly events" not in health["factors"]:
            health["factors"].append("Recent anomaly events")

        result = {
            "success": True,
            "asset_id": asset_id,
            "anomaly_detection": {
                "anomalies": anomalies,
                "anomalies_detected": len(anomalies),
                "total_analyzed": total_analyzed,
                "anomaly_rate_pct": anomaly_rate
            },
            "health": health
        }
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logging.exception(f"[ANALYZE_DIAGNOSTICS] {e}")
        notify_failure("Diagnostics Analysis", str(e), page="diagnostics", user_id=session.get('user_id'))
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@blueprint.post("/api/assets/{asset_id}/diagnostics/upload-logs")
@login_required
async def upload_diagnostic_logs(request: Request, asset_id: str):
    session = get_session(request)
    try:
        user_id = session.get('user_id')
        form = await request.form()
        file = form.get('file')
        if not file or not getattr(file, 'filename', None):
            return JSONResponse({'success': False, 'error': 'No file uploaded'}, status_code=400)

        from common.services.anomaly_detector import parse_instrument_logs
        file_content = await file.read()
        parsed_result = parse_instrument_logs(file_content, file.filename)

        if not parsed_result.get("success"):
            return JSONResponse({'success': False, 'error': parsed_result.get("error", "Failed to parse logs")}, status_code=400)

        from common.ai.rag.assets_rag import ingest_instrument_logs
        logs = parsed_result.get("logs", [])
        for log in logs:
            if not log.get("tag_number"):
                log["tag_number"] = asset_id

        ingest_result = ingest_instrument_logs(user_id, logs, asset_id=asset_id, source_file=file.filename)

        return JSONResponse({
            "success": True,
            "parsed_rows": parsed_result.get("row_count", 0),
            "ingested_success": ingest_result.get("success", False)
        }, status_code=200)
    except Exception as e:
        logging.exception(f"[UPLOAD_LOGS] {e}")
        notify_failure("Diagnostics Logs Upload", str(e), page="diagnostics", user_id=session.get('user_id'))
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@blueprint.get("/api/diagnostics/status")
@login_required
async def diagnostics_status(request: Request):
    session = get_session(request)
    try:
        from common.services.anomaly_detector import get_monitor_service
        svc = get_monitor_service()
        status = svc.get_status()

        user_id = session.get('user_id')
        total_anomalies = 0
        critical_count = 0
        last_detected_at = None
        try:
            from common.infra.mongodb_config import get_mongodb_connection
            conn = get_mongodb_connection()
            db_inst = conn.get('database')
            if db_inst is not None:
                try:
                    uid_int = int(user_id)
                    uid_query = {'$or': [{'user_id': user_id}, {'user_id': uid_int}]}
                except (ValueError, TypeError):
                    uid_query = {'user_id': user_id}
                total_anomalies = db_inst['anomaly_results'].count_documents(uid_query)
                critical_count = db_inst['anomaly_results'].count_documents({**uid_query, 'severity': 'critical', 'acknowledged': False})
                latest = db_inst['anomaly_results'].find_one(uid_query, sort=[('detected_at', -1)])
                if latest and latest.get('detected_at'):
                    last_detected_at = latest['detected_at'].isoformat()
        except Exception:
            pass

        return JSONResponse({
            'success': True,
            'monitor': {
                'running': status.get('running', False),
                'active_sources': status.get('active_sources', 0),
                'total_sources': status.get('total_sources', 0),
            },
            'anomaly_stats': {
                'total_anomalies': total_anomalies,
                'unacknowledged_critical': critical_count,
                'last_detected_at': last_detected_at,
            },
        })
    except Exception as e:
        logging.exception(f"[DIAG_STATUS] {e}")
        notify_failure("Diagnostics Status Fetch", str(e), page="diagnostics", user_id=session.get('user_id'))
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@blueprint.get("/api/diagnostics/anomalies")
@login_required
async def diagnostics_anomalies(request: Request):
    session = get_session(request)
    try:
        from common.infra.mongodb_config import get_mongodb_connection

        user_id = session.get('user_id')
        conn = get_mongodb_connection()
        db_inst = conn.get('database')
        if db_inst is None:
            return JSONResponse({'success': False, 'error': 'DB unavailable'}, status_code=500)

        try:
            uid_int = int(user_id)
            query: dict = {'$or': [{'user_id': user_id}, {'user_id': uid_int}]}
        except (ValueError, TypeError):
            query = {'user_id': user_id}

        since_str = request.query_params.get('since')
        if since_str:
            try:
                since_dt = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
                query["timestamp"] = {"$gte": since_dt}
            except Exception:
                pass

        tag = request.query_params.get('tag_number')
        if tag:
            query["tag_number"] = tag

        severity = request.query_params.get('severity')
        if severity:
            query["severity"] = severity

        if request.query_params.get('unacked_only') in ('1', 'true'):
            query["acknowledged"] = False

        try:
            limit = min(int(request.query_params.get('limit', 200)), 1000)
        except ValueError:
            limit = 200

        records = list(db_inst['anomaly_results'].find(query, {'_id': 0}).sort('detected_at', -1).limit(limit))

        for r in records:
            for field in ('detected_at', 'timestamp'):
                if isinstance(r.get(field), datetime):
                    r[field] = r[field].isoformat()

        return JSONResponse({'success': True, 'count': len(records), 'anomalies': records})
    except Exception as e:
        logging.exception(f"[DIAG_ANOMALIES] {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@blueprint.get("/api/diagnostics/health-summary")
@login_required
async def diagnostics_health_summary(request: Request):
    session = get_session(request)
    try:
        from common.infra.mongodb_config import get_mongodb_connection
        conn = get_mongodb_connection()
        db_inst = conn.get('database')
        if db_inst is None:
            return JSONResponse({'success': False, 'error': 'DB unavailable'}, status_code=500)

        pipeline = [
            {'$match': {}},
            {'$sort': {'detected_at': 1}},
            {'$group': {
                '_id': '$tag_number',
                'anomaly_count': {'$sum': 1},
                'avg_score': {'$avg': '$anomaly_score'},
                'max_score': {'$max': '$anomaly_score'},
                'critical_count': {'$sum': {'$cond': [{'$eq': ['$severity', 'critical']}, 1, 0]}},
                'last_detected_at': {'$last': '$detected_at'},
            }},
        ]
        rows = list(db_inst['anomaly_results'].aggregate(pipeline))

        summary: dict = {}
        for row in rows:
            tag = row['_id']
            if not tag:
                continue
            avg_score = float(row.get('avg_score') or 0)
            health_score = round(max(0.0, min(100.0, 100.0 - avg_score * 100)), 1)
            if health_score >= 80:
                health_status = 'healthy'
            elif health_score >= 50:
                health_status = 'warning'
            else:
                health_status = 'critical'
            last_dt = row.get('last_detected_at')
            summary[tag] = {
                'health_status': health_status,
                'health_score': health_score,
                'critical_flagged': health_status == 'critical',
                'anomaly_count': row.get('anomaly_count', 0),
                'last_detected_at': last_dt.isoformat() if isinstance(last_dt, datetime) else last_dt,
            }

        return JSONResponse({'success': True, 'summary': summary})
    except Exception as e:
        logging.exception(f"[DIAG_HEALTH] {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@blueprint.post("/api/diagnostics/monitor/sources")
@login_required
async def add_monitor_source(request: Request):
    session = get_session(request)
    try:
        from common.services.anomaly_detector import get_monitor_service

        user_id = session.get('user_id')
        try:
            body = await request.json()
        except Exception:
            body = {}

        path = body.get('path', '').strip()
        name = body.get('name', '').strip() or os.path.basename(path)
        poll_interval = max(10, int(body.get('poll_interval', 30)))
        asset_id = body.get('asset_id')

        if not path:
            return JSONResponse({'success': False, 'error': '"path" is required'}, status_code=400)

        svc = get_monitor_service()
        result = svc.add_source(user_id=user_id, path=path, name=name, poll_interval=poll_interval, asset_id=asset_id)
        return JSONResponse(result)
    except Exception as e:
        logging.exception(f"[ADD_SOURCE] {e}")
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)
