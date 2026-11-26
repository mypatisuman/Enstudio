from common.helpers.azure_session import get_session
"""Projects domain routes."""
import logging
import os
import requests
import uuid
from datetime import datetime, UTC
from fastapi import APIRouter, Request
from fastapi.responses import Response as FastAPIResponse
from app.core.security import login_required
from app.core.errors import notify_failure
from app.models.db.base import db
from app.models.db.user_model import User
from common.infra.repositories.project_repository import mongo_project_manager

from common.helpers.responses import JSONResponse

blueprint = APIRouter()


@blueprint.post("/api/projects/generate-name")
@login_required
async def generate_project_name(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    requirements = data.get("requirements", "").strip()
    if not requirements:
        return JSONResponse({"project_name": "Project"}, status_code=200)

    try:
        from common.ai.llm import get_solution_flash_llm
        llm = get_solution_flash_llm(temperature=0.2)
        
        prompt = (
            "Analyze the following user project requirements and generate a highly concise, descriptive project name.\n"
            "The name must be exactly 3 to 6 words long.\n"
            "Format the output strictly as the plain text of the name, with no quotes, preamble, or formatting.\n\n"
            f"Requirements:\n{requirements}\n\n"
            "Project Name:"
        )
        
        resp = llm.invoke(prompt)
        project_name = str(resp.content).strip()
        project_name = project_name.strip("\"'").strip()
        
        logging.info(f"[GENERATE_NAME] Generated project name: '{project_name}' from requirements prefix: '{requirements[:100]}'")
        return JSONResponse({"project_name": project_name}, status_code=200)
    except Exception as e:
        logging.exception("Failed to generate project name via LLM")
        return JSONResponse({"project_name": "Project"}, status_code=200)


@blueprint.post("/api/projects/save")
@login_required
async def save_project(request: Request):
    session = get_session(request)
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}

        try:
            incoming_pt = data.get('product_type') if isinstance(data, dict) else None
            incoming_detected = data.get('detected_product_type') if isinstance(data, dict) else None
            logging.info(f"[SAVE_PROJECT] Incoming product_type='{incoming_pt}' detected_product_type='{incoming_detected}' project_name='{data.get('project_name') if isinstance(data, dict) else None}' user_id={session.get('user_id')}")
        except Exception:
            logging.exception("Failed to log incoming project save payload")

        user_id = str(session['user_id'])
        data.get("project_id")
        project_name = data.get("project_name", "").strip()

        if not project_name:
            return JSONResponse({"error": "Project name is required"}, status_code=400)

        has_requirements = bool(data.get("initial_requirements", "").strip())
        has_instruments = bool(data.get("identified_instruments") and len(data.get("identified_instruments", [])) > 0)
        has_accessories = bool(data.get("identified_accessories") and len(data.get("identified_accessories", [])) > 0)

        is_initialization = bool(data.get("is_initialization", False))
        if not has_requirements and not has_instruments and not has_accessories and not is_initialization:
            return JSONResponse({"error": "Initial requirements are required"}, status_code=400)

        try:
            displayed_media = data.get('displayed_media_map', {}) if isinstance(data, dict) else {}
            if displayed_media:
                import re
                from common.infra.azure_blob import azure_blob_manager

                def normalize(name):
                    name = name.lower().strip()
                    name = re.sub(r'[^\w\s-]', '', name)
                    name = re.sub(r'[-\s]+', '_', name)
                    return name.strip('_') or 'unknown'

                product_type = data.get('product_type', 'unknown')

                for key, entry in displayed_media.items():
                    try:
                        top = entry.get('top_image') if isinstance(entry, dict) else None
                        vlogo = entry.get('vendor_logo') if isinstance(entry, dict) else None
                        generic = entry.get('generic_image') if isinstance(entry, dict) else None

                        def process_media(obj, subtype, key_param, product_type_param):
                            if not obj:
                                return None
                            url = obj.get('url') if isinstance(obj, dict) else (obj if isinstance(obj, str) else None)
                            if not url:
                                return None
                            if url.startswith('https://') and 'blob.core.windows.net' in url:
                                return url
                            if url.startswith('/api/projects/file/'):
                                return url
                            parts = key_param.split('-', 1)
                            vendor_name = parts[0] if len(parts) > 0 else 'unknown'
                            product_name = parts[1] if len(parts) > 1 else 'unknown'
                            vendor_normalized = normalize(vendor_name)
                            product_normalized = normalize(product_name)
                            product_type_normalized = normalize(product_type_param) if product_type_param else 'unknown'
                            file_bytes = None
                            content_type = 'image/jpeg'
                            if url.startswith('data:'):
                                import base64
                                m = re.match(r'data:(.*?);base64,(.*)', url)
                                if m:
                                    content_type = m.group(1)
                                    file_bytes = base64.b64decode(m.group(2))
                            else:
                                try:
                                    resp = requests.get(url, timeout=8)
                                    resp.raise_for_status()
                                    content_type = resp.headers.get('Content-Type', 'image/jpeg')
                                    file_bytes = resp.content
                                except Exception as e:
                                    logging.warning(f"Failed to fetch media URL {url}: {e}")
                                    return None
                            if not file_bytes:
                                return None
                            try:
                                if subtype == 'vendor_logo':
                                    blob_info = azure_blob_manager.upload_vendor_logo(file_bytes=file_bytes, vendor_name_normalized=vendor_normalized, content_type=content_type)
                                elif subtype == 'top_image':
                                    blob_info = azure_blob_manager.upload_product_image(file_bytes=file_bytes, product_type_normalized=product_type_normalized, vendor_name_normalized=vendor_normalized, model_family_normalized=product_normalized, content_type=content_type)
                                elif subtype == 'generic_image':
                                    blob_info = azure_blob_manager.upload_generic_image(file_bytes=file_bytes, product_type_normalized=product_type_normalized, content_type=content_type)
                                else:
                                    logging.warning(f"Unknown media subtype: {subtype}")
                                    return None
                                return blob_info['blobUrl']
                            except Exception as e:
                                logging.error(f"Failed to upload {subtype} to Azure Blob: {e}")
                                return None

                        new_top = process_media(top, 'top_image', key, product_type)
                        new_logo = process_media(vlogo, 'vendor_logo', key, product_type)
                        new_generic = process_media(generic, 'generic_image', key, product_type)

                        if new_top or new_logo or new_generic:
                            if 'embedded_media' not in data:
                                data['embedded_media'] = {}
                            data['embedded_media'][key] = {}
                            if new_top:
                                data['embedded_media'][key]['top_image'] = {'url': new_top}
                            if new_logo:
                                data['embedded_media'][key]['vendor_logo'] = {'url': new_logo}
                            if new_generic:
                                data['embedded_media'][key]['generic_image'] = {'url': new_generic}
                    except Exception as e:
                        logging.warning(f"Error processing displayed_media_map entry {key}: {e}")
        except Exception as e:
            logging.warning(f"Failed to persist displayed_media_map: {e}")

        try:
            if 'feedback' in data and 'feedback_entries' not in data:
                data['feedback_entries'] = data.get('feedback')
        except Exception:
            logging.warning('Failed to normalize incoming feedback payload')

        saved_project = mongo_project_manager.save_project(user_id, data)

        try:
            session['current_project_id'] = saved_project.get('project_id')
        except Exception:
            logging.warning('Failed to set current_project_id in session')

        try:
            incoming_session_id = data.get("session_id") if isinstance(data, dict) else None
            saved_project_id = saved_project.get('project_id') or saved_project.get('id')
            if incoming_session_id and saved_project_id:
                from common.ai.memory.core import mark_session_saved
                mark_session_saved(incoming_session_id, str(saved_project_id))
        except Exception:
            logging.warning('Failed to mark session as saved for TTL exemption')

        return JSONResponse(content={"message": "Project saved successfully", "project": saved_project}, status_code=200)

    except ValueError as e:
        logging.warning(f"Project save validation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=409)
    except Exception as e:
        logging.exception("Project save failed.")
        notify_failure("Project Save", str(e), page="projects", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to save project: " + str(e)}, status_code=500)


@blueprint.post("/api/projects/match")
@login_required
async def match_saved_projects(request: Request):
    """Episodic recall step 1: does this request match a saved project?"""
    session = get_session(request)
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}

        user_id = str(session['user_id'])
        query = (data.get("query") or data.get("user_input") or "").strip()
        session_id = data.get("session_id") or session.get("session_id") or ""

        if not query:
            return JSONResponse({"error": "query is required"}, status_code=400)

        from app.services.project_service import match_saved_projects as _match
        result = _match(user_id, session_id, query)
        return JSONResponse(content=result, status_code=200)

    except Exception as e:
        logging.exception("Project match failed.")
        notify_failure("Project Match", str(e), page="projects", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to match saved projects: " + str(e)}, status_code=500)


@blueprint.post("/api/projects/recall/ignore")
@login_required
async def ignore_recall(request: Request):
    """Episodic recall: user clicked Ignore — decline and return the original query for a fresh run."""
    session = get_session(request)
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}

        session_id = data.get("session_id") or session.get("session_id") or ""

        from app.services.project_service import decline_recall as _decline
        result = _decline(session_id)
        return JSONResponse(content=result, status_code=200)

    except Exception as e:
        logging.exception("Project recall ignore failed.")
        notify_failure("Project Recall Ignore", str(e), page="projects", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to ignore recall: " + str(e)}, status_code=500)


@blueprint.post("/api/projects/recall/dismiss")
@login_required
async def dismiss_recall(request: Request):
    """Clear a pending recall offer without retrieving.

    Used when the user resolves the 'Repeated Request Detected' dialog by clicking
    Open (which loads the project directly) so the NEXT message isn't misread as a
    reply to the offer. Idempotent; safe to call when nothing is pending.
    """
    session = get_session(request)
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}

        session_id = data.get("session_id") or session.get("session_id") or ""
        if session_id:
            from common.ai.memory import clear_pending_recall
            clear_pending_recall(session_id)
        return JSONResponse({"cleared": bool(session_id)}, status_code=200)
    except Exception as e:
        logging.exception("Recall dismiss failed.")
        return JSONResponse({"error": "Failed to dismiss recall: " + str(e)}, status_code=500)


@blueprint.get("/api/projects")
@login_required
async def get_user_projects(request: Request):
    session = get_session(request)
    try:
        user_id = str(session['user_id'])
        projects = mongo_project_manager.get_user_projects(user_id)
        return JSONResponse(content={"projects": projects, "total_count": len(projects)}, status_code=200)
    except Exception as e:
        logging.exception("Failed to retrieve user projects.")
        notify_failure("User Projects Fetch", str(e), page="projects", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to retrieve projects: " + str(e)}, status_code=500)


@blueprint.get("/api/projects/{project_id}")
@login_required
async def get_project_details(request: Request, project_id: str):
    session = get_session(request)
    try:
        user_id = str(session['user_id'])
        project_details = mongo_project_manager.get_project_details(project_id, user_id)
        return JSONResponse({"project": project_details}, status_code=200)
    except ValueError as e:
        logging.warning(f"Project access denied: {e}")
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        logging.exception(f"Failed to retrieve project {project_id}.")
        notify_failure("Project Details Fetch", str(e), page="projects", user_id=session.get('user_id'))
        return JSONResponse({"error": "Failed to retrieve project: " + str(e)}, status_code=500)


@blueprint.get("/api/projects/file/{file_id}")
@login_required
async def serve_project_file(request: Request, file_id: str):
    session = get_session(request)
    try:
        from bson import ObjectId
        from common.infra.mongodb_utils import mongodb_file_manager
        user_id = str(session['user_id'])

        try:
            oid = ObjectId(file_id)
            is_gridfs_id = True
        except Exception:
            is_gridfs_id = False

        if is_gridfs_id:
            try:
                document = mongodb_file_manager.db['documents'].find_one({'_id': oid})
                if document and document.get('blob_url'):
                    blob_url = document['blob_url']
                    from common.infra.blob_sas import generate_sas_url
                    sas_url = generate_sas_url(blob_url, expiry_hours=24)
                    if not sas_url:
                        sas_url = blob_url
                    return JSONResponse({"file_url": sas_url}, status_code=200)
            except Exception:
                logging.debug(f"Not found in documents collection: {file_id}")

            try:
                if mongodb_file_manager.gridfs:
                    grid_file = mongodb_file_manager.gridfs.get(oid)
                    data = grid_file.read()
                    content_type = grid_file.content_type if hasattr(grid_file, 'content_type') else grid_file.metadata.get('content_type') if getattr(grid_file, 'metadata', None) else 'application/octet-stream'
                    return FastAPIResponse(
                        content=data,
                        status_code=200,
                        media_type=content_type,
                        headers={'Cache-Control': 'public, max-age=31536000'}
                    )
            except Exception:
                logging.debug(f"GridFS file not found: {file_id}, trying as project_id")

        try:
            project_meta = mongo_project_manager.file_manager.db['user_projects'].find_one({
                '_id': ObjectId(file_id),
                'user_id': user_id
            })

            if not project_meta:
                return JSONResponse({"error": "File not found"}, status_code=404)

            storage_format = project_meta.get('storage_format', 'gridfs')

            if storage_format == 'azure_blob':
                blob_info = project_meta.get('blob_info')
                if not blob_info:
                    return JSONResponse({"error": "Blob info not found"}, status_code=404)
                from common.infra.blob_sas import generate_sas_url
                sas_url = generate_sas_url(blob_info['blobUrl'], expiry_hours=24)
                if not sas_url:
                    sas_url = blob_info['blobUrl']
                return JSONResponse({"file_url": sas_url}, status_code=200)

            elif storage_format == 'gridfs':
                gridfs_file_id = project_meta.get('gridfs_file_id')
                if gridfs_file_id and mongodb_file_manager.gridfs:
                    grid_file = mongodb_file_manager.gridfs.get(ObjectId(gridfs_file_id))
                    data = grid_file.read()
                    return FastAPIResponse(content=data, status_code=200, media_type='application/json', headers={'Content-Length': str(len(data))})

        except Exception:
            logging.exception(f"Failed to serve file {file_id}")
            return JSONResponse({"error": "Failed to retrieve file"}, status_code=500)

        return JSONResponse({"error": "File not found"}, status_code=404)

    except Exception as e:
        logging.exception('Failed to serve project file')
        notify_failure("Project File Serve", str(e), page="projects", user_id=session.get('user_id'))
        return JSONResponse({'error': str(e)}, status_code=500)


@blueprint.delete("/api/projects/{project_id}")
@login_required
async def delete_project(request: Request, project_id: str):
    session = get_session(request)
    try:
        user_id = str(session['user_id'])
        mongo_project_manager.delete_project(project_id, user_id)
        return JSONResponse({"message": "Project deleted successfully"}, status_code=200)
    except ValueError as e:
        logging.warning(f"Project delete access denied: {e}")
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        logging.exception(f"Failed to delete project {project_id}.")
        return JSONResponse({"error": "Failed to delete project: " + str(e)}, status_code=500)
