from common.helpers.azure_session import get_session
"""Uploads domain routes."""
import json
import logging
import threading
from datetime import datetime, UTC
from app.core.security import login_required
from app.core.security import validate_uploaded_file, secure_filename
from app.core.errors import notify_failure
from common.infra.mongodb_config import get_mongodb_connection

from fastapi import APIRouter, Request
from common.helpers.responses import JSONResponse

blueprint = APIRouter()


async def _parse_multipart_file(request: Request):
    """Parse multipart form data for file upload. Returns (file_obj, filename) or (None, None)."""
    try:
        form = await request.form()
        if 'file' in form:
            f = form['file']
            return f, getattr(f, 'filename', None)
    except Exception:
        pass

    try:
        from io import BytesIO
        ct = request.headers.get('Content-Type', '')
        body = await request.body()
        if not body or not ct.startswith('multipart/form-data'):
            return None, None
        boundary = ct.split('boundary=')[1].split(';')[0].encode()
        for part in body.split(b'--' + boundary):
            if b'Content-Disposition: form-data' in part and b'name="file"' in part:
                headers_end = part.find(b'\r\n\r\n')
                if headers_end != -1:
                    file_data = part[headers_end + 4:]
                    if file_data.endswith(b'\r\n'):
                        file_data = file_data[:-2]
                    headers_str = part[:headers_end].decode('utf-8', errors='ignore')
                    fn = headers_str.split('filename="')[1].split('"')[0] if 'filename="' in headers_str else 'uploaded_file'
                    file_obj = BytesIO(file_data)
                    file_obj.name = fn
                    file_obj.filename = fn
                    file_obj.content_type = 'application/octet-stream'
                    return file_obj, fn
    except Exception as e:
        logging.warning(f"[UPLOAD] Manual multipart parse failed: {e}")

    return None, None


# =========================================================================
# === FILE UPLOAD AND TEXT EXTRACTION ENDPOINT ===
# =========================================================================
@blueprint.post("/api/upload-requirements")
@login_required
async def upload_requirements_file(request: Request):
    session = get_session(request)

    """
    Upload file (PDF, DOCX, TXT, Images) and extract text as requirements

    Accepts: multipart/form-data with one or more 'file' fields
    Returns: Combined extracted text from all uploaded files
    """
    try:
        from common.services.file_extractor import extract_text_from_file

        logging.info("[API] ===== File Upload Request START =====")

        # Check if file(s) are present
        if 'file' not in (form_data := await request.form()):
            logging.warning("[API] No file provided in request")
            return JSONResponse({
                "success": False,
                "error": "No file provided"
            }, status_code=400)

        files = [f for f in form_data.getlist('file') if f and f.filename]
        if not files:
            logging.warning("[API] Empty filename")
            return JSONResponse({
                "success": False,
                "error": "No file selected"
            }, status_code=400)

        logging.info(f"[API] Processing {len(files)} file(s) for combined extraction")

        combined_parts = []
        processed_files = []
        for file in files:
            filename = file.filename
            file_bytes = await file.read()
            logging.info(f"[API] Processing file: {filename} ({len(file_bytes)} bytes)")

            extraction_result = extract_text_from_file(file_bytes, filename)
            if not extraction_result['success']:
                logging.warning(f"[API] Failed to extract text from {filename}")
                return JSONResponse({
                    "success": False,
                    "error": f"Could not extract text from {filename} ({extraction_result['file_type']} file)",
                    "file_type": extraction_result['file_type'],
                    "filename": filename
                }, status_code=400)

            extracted_text = extraction_result.get('extracted_text', '').strip()
            if extracted_text:
                combined_parts.append(f"--- {filename} ---\n{extracted_text}")

            processed_files.append({
                "filename": filename,
                "file_type": extraction_result['file_type'],
                "character_count": extraction_result['character_count']
            })

        combined_text = "\n\n".join(combined_parts)
        total_chars = len(combined_text)
        if not combined_text:
            return JSONResponse({
                "success": False,
                "error": "No text extracted from provided files"
            }, status_code=400)

        logging.info(f"[API] Successfully extracted combined text ({total_chars} chars) from {len(processed_files)} file(s)")
        logging.info("[API] ===== File Upload Request END (SUCCESS) =====")

        return JSONResponse({
            "success": True,
            "extracted_text": combined_text,
            "file_count": len(processed_files),
            "files": processed_files,
            "character_count": total_chars
        }, status_code=200)

    except Exception as e:
        logging.exception(f"[API] ERROR processing file upload: {e}")
        logging.info("[API] ===== File Upload Request END (ERROR) =====")
        notify_failure("File Upload Processing", str(e), page="uploads", user_id=session.get('user_id'))
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


# =========================================================================
# === STRATEGY FILE UPLOAD — CSV + EMBEDDINGS ===
# =========================================================================
@blueprint.post("/api/upload-strategy-file")
@login_required
async def upload_strategy_file(request: Request):
    session = get_session(request)
    try:
        file, filename = await _parse_multipart_file(request)
        if not file:
            return JSONResponse({"success": False, "error": "No file provided"}, status_code=400)

        from io import BytesIO as _BytesIO
        file_bytes = await file.read()
        if not file_bytes:
            return JSONResponse({"success": False, "error": "Uploaded file is empty"}, status_code=400)

        _vf = _BytesIO(file_bytes)
        _vf.filename = filename or getattr(file, 'filename', 'file.csv')
        validation = validate_uploaded_file(_vf, allowed_extensions=['.csv'])
        if not validation['valid']:
            return JSONResponse({"success": False, "error": validation['error']}, status_code=400)

        filename = filename or validation['filename']
        content_type = getattr(file, 'content_type', None) or 'text/csv'

        user_id = session.get('user_id')
        if not user_id:
            return JSONResponse({"success": False, "error": "User not authenticated"}, status_code=401)

        from common.infra.azure_blob import azure_blob_manager
        from app.services.upload_service import _queue_llm_task

        # 1. Upload raw file to blob storage first
        blob_info = azure_blob_manager.upload_strategy_document(file_bytes, filename, int(user_id), content_type)
        blob_url = blob_info.get("blobUrl")
        
        if not blob_url:
            return JSONResponse({"success": False, "error": "Failed to upload document to storage"}, status_code=500)

        # 2. Add an initial "processing" record to MongoDB
        conn = get_mongodb_connection()
        conn['collections']['stratergy'].update_one(
            {"user_id": user_id, "filename": filename},
            {"$set": {
                "uploaded_at": datetime.now(UTC).isoformat(),
                "extraction_method": "upload_time_embeddings",
                "storage": blob_info,
                "status": "processing"
            }},
            upsert=True,
        )

        # 3. Queue the embedding creation background task
        success = _queue_llm_task({
            "type": "strategy_upload",
            "user_id": user_id,
            "filename": filename,
            "blob_url": blob_url
        })
        
        if not success:
            # Fallback if queue is somehow down
            logging.warning("[STRATEGY_UPLOAD] Queue unavailable, fallback to synchronous")
            from app.services.upload_service import process_strategy_blob_for_rag
            import threading
            threading.Thread(target=process_strategy_blob_for_rag, args=(user_id, filename, blob_url), daemon=True).start()

        return JSONResponse({
            "success": True,
            "queued": True,
            "message": f"Strategy file '{filename}' uploaded successfully and is being processed.",
            "filename": filename,
        }, status_code=202)

    except Exception as e:
        logging.exception(f"[STRATEGY_UPLOAD] ERROR: {e}")
        notify_failure("Strategy File Upload Processing", str(e), page="uploads", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# =========================================================================
# === ASSETS FILE UPLOAD — CSV stored in blob ===
# =========================================================================
@blueprint.post("/api/upload-assets-file")
@login_required
async def upload_assets_file(request: Request):
    session = get_session(request)
    try:
        file, filename = await _parse_multipart_file(request)
        if not file:
            return JSONResponse({"success": False, "error": "No file provided"}, status_code=400)

        from io import BytesIO as _BytesIO
        file_bytes = await file.read()
        if not file_bytes:
            return JSONResponse({"success": False, "error": "Uploaded file is empty"}, status_code=400)

        _vf = _BytesIO(file_bytes)
        _vf.filename = filename or getattr(file, 'filename', 'file.csv')
        validation = validate_uploaded_file(_vf, allowed_extensions=['.csv'])
        if not validation['valid']:
            return JSONResponse({"success": False, "error": validation['error']}, status_code=400)

        filename = filename or validation['filename']
        content_type = getattr(file, 'content_type', None) or 'text/csv'

        user_id = session.get('user_id')
        if not user_id:
            return JSONResponse({"success": False, "error": "User not authenticated"}, status_code=401)

        from common.infra.azure_blob import azure_blob_manager
        from app.services.upload_service import _queue_llm_task

        # 1. Upload raw file to blob storage first
        blob_info = azure_blob_manager.upload_assets_document(file_bytes, filename, int(user_id), content_type)
        blob_url = blob_info.get("blobUrl")
        
        if not blob_url:
            return JSONResponse({"success": False, "error": "Failed to upload document to storage"}, status_code=500)

        # 2. Add an initial "processing" record to MongoDB
        conn = get_mongodb_connection()
        conn['collections']['assets'].update_one(
            {"user_id": user_id, "filename": filename},
            {"$set": {
                "uploaded_at": datetime.now(UTC).isoformat(),
                "extraction_method": "csv_direct_parse",
                "storage": blob_info,
                "status": "processing"
            }},
            upsert=True,
        )

        # 3. Queue the embedding creation background task
        success = _queue_llm_task({
            "type": "assets_upload",
            "user_id": user_id,
            "filename": filename,
            "blob_url": blob_url
        })
        
        if not success:
            # Fallback if queue is somehow down
            logging.warning("[ASSETS_UPLOAD] Queue unavailable, fallback to synchronous")
            from app.services.upload_service import process_assets_blob_for_rag
            import threading
            threading.Thread(target=process_assets_blob_for_rag, args=(user_id, filename, blob_url), daemon=True).start()

        return JSONResponse({
            "success": True,
            "queued": True,
            "message": f"Assets file '{filename}' uploaded successfully and is being processed.",
            "filename": filename,
        }, status_code=202)

    except Exception as e:
        logging.exception(f"[ASSETS_UPLOAD] ERROR: {e}")
        notify_failure("Assets File Upload Processing", str(e), page="uploads", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# =========================================================================
# === STANDARDS FILE UPLOAD ENDPOINT ===
# =========================================================================
@blueprint.post("/api/upload-standards-file")
@login_required
async def upload_standards_file(request: Request):
    session = get_session(request)

    try:
        file, filename = await _parse_multipart_file(request)
        if not file:
            return JSONResponse({"success": False, "error": "No file provided"}, status_code=400)

        from io import BytesIO as _BytesIO
        file_bytes = await file.read()
        if not file_bytes:
            return JSONResponse({"success": False, "error": "Uploaded file is empty"}, status_code=400)

        allowed_exts = ['.pdf', '.docx', '.doc', '.txt']
        _vf = _BytesIO(file_bytes)
        _vf.filename = filename or getattr(file, 'filename', 'file')
        validation = validate_uploaded_file(_vf, allowed_extensions=allowed_exts)
        if not validation['valid']:
            return JSONResponse({"success": False, "error": validation['error']}, status_code=400)

        filename = filename or validation['filename']
        content_type = getattr(file, 'content_type', None) or 'application/octet-stream'

        user_id = session.get('user_id')
        if not user_id:
            return JSONResponse({"success": False, "error": "User not authenticated"}, status_code=401)

        def _run():
            try:
                from app.services.upload_service import extract_and_store_standards_text
                from common.infra.azure_blob import azure_blob_manager

                blob_info = azure_blob_manager.upload_standards_document(
                    file_bytes=file_bytes, filename=filename,
                    user_id=user_id, content_type=content_type,
                )
                blob_url = blob_info.get('blobUrl') if isinstance(blob_info, dict) else None
                if not blob_url:
                    logging.error(f"[STANDARDS_UPLOAD] Blob URL missing for {filename}")
                    return
                result = extract_and_store_standards_text(file_bytes, filename, int(user_id), blob_url)
                if result.get("success"):
                    logging.info(f"[STANDARDS_UPLOAD] ✓ Done: {filename}")
                else:
                    logging.error(f"[STANDARDS_UPLOAD] Extraction failed: {result.get('error')}")
            except Exception as e:
                logging.exception(f"[STANDARDS_UPLOAD] Background error: {e}")

        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({
            "success": True,
            "message": f"Standards document '{filename}' uploaded successfully.",
            "filename": filename,
        }, status_code=200)

    except Exception as e:
        logging.exception(f"[STANDARDS_UPLOAD] ERROR: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
