"""
flask_compat.py — High-performance bridge between FastAPI/Starlette and controller logic.
Provides request, g, jsonify, render_template, send_from_directory, send_file, Response,
FlaskCompatRoute, FlaskCompatMiddleware, FastAPICompat, and Blueprint.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import io
import json
import os
import re
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional, Union

from fastapi import FastAPI, APIRouter
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response as StarletteResponse,
    StreamingResponse,
)
from starlette.templating import Jinja2Templates

_request_ctx: ContextVar[Optional[Request]] = ContextVar("_request_ctx", default=None)
_g_ctx: ContextVar[Any] = ContextVar("_g_ctx", default=None)

# Initialize templates pointing to backend/templates
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class FileStorageCompat:
    """Wrapper for UploadFile to provide Flask-like .read(), .filename, .content_type."""
    def __init__(self, filename: str, content: bytes, content_type: str = ""):
        self.filename = filename
        self._content = content
        self.content_type = content_type

    def read(self) -> bytes:
        return self._content


class RequestProxy:
    """Proxy object simulating Flask's thread/task-local request."""
    @property
    def _req(self) -> Request:
        req = _request_ctx.get()
        if req is None:
            raise RuntimeError("Working outside of request context")
        return req

    @property
    def method(self) -> str:
        return self._req.method

    @property
    def path(self) -> str:
        return self._req.url.path

    @property
    def headers(self):
        return self._req.headers

    @property
    def args(self):
        # Query params as dict-like object
        return self._req.query_params

    @property
    def query_params(self):
        return self._req.query_params

    @property
    def view_args(self):
        return getattr(self._req.state, "view_args", {}) or self._req.path_params

    def get_json(self, force: bool = False, silent: bool = False) -> Any:
        if hasattr(self._req.state, "_json"):
            return self._req.state._json
        raw_body = getattr(self._req.state, "_body", None)
        if raw_body:
            try:
                self._req.state._json = json.loads(raw_body.decode("utf-8"))
                return self._req.state._json
            except Exception:
                if not silent:
                    raise
                return None
        return None

    @property
    def json(self) -> Any:
        return self.get_json(silent=True) or {}

    @property
    def files(self) -> dict:
        return getattr(self._req.state, "_files", {}) or {}

    @property
    def form(self) -> dict:
        return getattr(self._req.state, "_form", {}) or {}


request = RequestProxy()


class GProxy:
    """Proxy object simulating Flask's g namespace."""
    def __getattr__(self, name: str) -> Any:
        req = _request_ctx.get()
        if req is not None and hasattr(req.state, name):
            return getattr(req.state, name)
        g_obj = _g_ctx.get()
        if g_obj is not None:
            return getattr(g_obj, name, None)
        return None

    def __setattr__(self, name: str, value: Any) -> None:
        req = _request_ctx.get()
        if req is not None:
            setattr(req.state, name, value)
        g_obj = _g_ctx.get()
        if g_obj is not None:
            setattr(g_obj, name, value)


g = GProxy()


def jsonify(data: Any = None, *args: Any, **kwargs: Any) -> JSONResponse:
    if data is None and kwargs:
        data = kwargs
    elif data is not None and kwargs:
        if isinstance(data, dict):
            data = dict(data)
            data.update(kwargs)
    elif data is None:
        data = {}
    return JSONResponse(content=data)


def Response(
    content: Any = b"",
    status: int = 200,
    mimetype: str = "text/plain",
    headers: Optional[dict] = None,
    **kwargs: Any
) -> StarletteResponse:
    media_type = kwargs.get("media_type") or mimetype
    return StarletteResponse(content=content, status_code=status, media_type=media_type, headers=headers)


def render_template(template_name: str, **context: Any) -> HTMLResponse:
    req = _request_ctx.get()
    if req is not None:
        return templates.TemplateResponse(request=req, name=template_name, context=context)
    # Standalone render fallback
    template = templates.get_template(template_name)
    rendered = template.render(**context)
    return HTMLResponse(content=rendered)


def send_from_directory(
    directory: Union[str, Path],
    filename: str,
    as_attachment: bool = False,
    **kwargs: Any
) -> FileResponse:
    file_path = Path(directory) / filename
    headers = {}
    if as_attachment:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return FileResponse(str(file_path), headers=headers)


def send_file(
    path_or_file: Union[str, Path, io.BytesIO],
    mimetype: Optional[str] = None,
    as_attachment: bool = False,
    download_name: Optional[str] = None,
    **kwargs: Any
) -> StarletteResponse:
    headers = {}
    if isinstance(path_or_file, io.BytesIO):
        if as_attachment and download_name:
            headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
        path_or_file.seek(0)
        return StreamingResponse(path_or_file, media_type=mimetype or "application/octet-stream", headers=headers)

    path = str(path_or_file)
    if as_attachment:
        name = download_name or Path(path).name
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return FileResponse(path, media_type=mimetype, headers=headers)


def _flask_to_fastapi_rule(rule: str) -> str:
    rule = re.sub(r'<int:([^>]+)>', r'{\1:int}', rule)
    rule = re.sub(r'<path:([^>]+)>', r'{\1:path}', rule)
    rule = re.sub(r'<([^>]+)>', r'{\1}', rule)
    return rule


def wrap_endpoint(endpoint: Callable) -> Callable:
    """Wrap route handler to ensure context propagation and (body, status_code) tuple support."""
    @functools.wraps(endpoint)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        if asyncio.iscoroutinefunction(endpoint):
            res = await endpoint(*args, **kwargs)
        else:
            res = await run_in_threadpool(endpoint, *args, **kwargs)

        status_code = None
        headers = None
        if isinstance(res, tuple):
            if len(res) == 2:
                res, status_code = res
            elif len(res) == 3:
                res, status_code, headers = res

        if isinstance(res, StarletteResponse):
            if status_code is not None:
                res.status_code = status_code
            if headers:
                for k, v in headers.items():
                    res.headers[k] = v
            return res
        elif isinstance(res, (dict, list)):
            return JSONResponse(content=res, status_code=status_code or 200, headers=headers)
        elif isinstance(res, str):
            return HTMLResponse(content=res, status_code=status_code or 200, headers=headers)
        elif res is None:
            return StarletteResponse(status_code=status_code or 204)
        return res

    return wrapped


class FlaskCompatRoute(APIRoute):
    """Custom APIRoute that automatically wraps controller endpoints for Flask return types."""
    def __init__(self, path: str, endpoint: Callable, **kwargs: Any):
        wrapped = wrap_endpoint(endpoint)
        super().__init__(path, wrapped, **kwargs)


class Blueprint:
    """Blueprint compatibility shim for APIRouter."""
    def __init__(self, name: str, import_name: str = "", url_prefix: str = ""):
        self.name = name
        self.url_prefix = url_prefix
        self.router = APIRouter(prefix=url_prefix, route_class=FlaskCompatRoute)

    def route(self, rule: str, **options: Any):
        return self.router.api_route(_flask_to_fastapi_rule(rule), **options)

    def get(self, rule: str, **options: Any):
        return self.router.get(_flask_to_fastapi_rule(rule), **options)

    def post(self, rule: str, **options: Any):
        return self.router.post(_flask_to_fastapi_rule(rule), **options)

    def put(self, rule: str, **options: Any):
        return self.router.put(_flask_to_fastapi_rule(rule), **options)

    def delete(self, rule: str, **options: Any):
        return self.router.delete(_flask_to_fastapi_rule(rule), **options)

    def after_request(self, fn: Any) -> Any:
        return fn

    def before_request(self, fn: Any) -> Any:
        return fn


class FlaskCompatMiddleware(BaseHTTPMiddleware):
    """Binds incoming ASGI Request to thread/task local context and parses JSON/multipart."""
    async def dispatch(self, request: Request, call_next):
        token_req = _request_ctx.set(request)
        token_g = _g_ctx.set(request.state)

        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            try:
                form = await request.form()
                files = {}
                form_data = {}
                for key, value in form.multi_items():
                    if hasattr(value, "filename") and hasattr(value, "read"):
                        content = await value.read()
                        files[key] = FileStorageCompat(
                            filename=value.filename or "",
                            content=content,
                            content_type=value.content_type or ""
                        )
                    else:
                        form_data[key] = value
                request.state._files = files
                request.state._form = form_data
            except Exception:
                pass
        else:
            try:
                body = await request.body()
                request.state._body = body
                if body:
                    try:
                        request.state._json = json.loads(body.decode("utf-8"))
                    except Exception:
                        request.state._json = None
                else:
                    request.state._json = None
            except Exception:
                request.state._body = b""
                request.state._json = None

        try:
            response = await call_next(request)
            return response
        finally:
            _request_ctx.reset(token_req)
            _g_ctx.reset(token_g)


class FastAPICompat(FastAPI):
    """FastAPI wrapper offering Flask-like @app.route, @app.errorhandler, and config."""
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.router.route_class = FlaskCompatRoute
        self.config = {"TEMPLATES_AUTO_RELOAD": True}
        self.add_middleware(FlaskCompatMiddleware)

    def route(self, path: str, methods: list[str] | None = None, **kwargs: Any):
        methods = [m.upper() for m in (methods or ["GET"])]
        rule = _flask_to_fastapi_rule(path)
        return self.router.api_route(rule, methods=methods, **kwargs)

    def register_blueprint(self, blueprint: Any, **kwargs: Any):
        if hasattr(blueprint, "router"):
            self.include_router(blueprint.router, **kwargs)

    def errorhandler(self, exc_class: type[Exception]):
        def decorator(fn: Any):
            @self.exception_handler(exc_class)
            async def _handler(request: Request, exc: Exception):
                token_req = _request_ctx.set(request)
                token_g = _g_ctx.set(request.state)
                try:
                    if asyncio.iscoroutinefunction(fn):
                        res = await fn(exc)
                    else:
                        res = await run_in_threadpool(fn, exc)
                    status = 500
                    if isinstance(res, tuple):
                        res_obj, status = res[0], res[1]
                        if isinstance(res_obj, StarletteResponse):
                            res_obj.status_code = status
                            return res_obj
                        return JSONResponse(content=res_obj, status_code=status)
                    return res
                finally:
                    _request_ctx.reset(token_req)
                    _g_ctx.reset(token_g)
            return fn
        return decorator
