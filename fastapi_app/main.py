"""
FastAPI application for Django LLM REST API.

Runs alongside Django on port 8001.
NGINX routes /api/ requests here.

Shares Django's database and session authentication.
"""

import os
import sys
import django
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
import time
import threading
from collections import deque

# Third-party imports (must be at module level)
from asgiref.sync import sync_to_async
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    Depends,
)
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.conf import settings
from django.contrib.auth.models import User
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Local imports (must be before django.setup())
from fastapi_app.routers import llm, convert, chat, health
from fastapi_app.logging_utils import (
    generate_request_id, get_structured_logger, get_client_ip
)

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsite.settings")
django.setup()

# Local imports (after django.setup())
from fastapi_app.routers import llm, convert, chat, health
from fastapi_app.logging_utils import (
    generate_request_id, get_structured_logger, get_client_ip
)
from fastapi_app.auth import get_current_user

logger = logging.getLogger(__name__)
structured_logger = get_structured_logger(__name__)

# -------------------------
# Rate Limiting
# -------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# -------------------------
# Environment Configuration
# -------------------------


def parse_env_list(value: Optional[str], default: list) -> list:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_env_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes", "on")


FASTAPI_TITLE = os.environ.get("FASTAPI_TITLE", "Django LLM API")
FASTAPI_DESCRIPTION = os.environ.get(
    "FASTAPI_DESCRIPTION",
    (
        "REST API for the Django LLM project. "
        "Provides access to LLM entries, conversions, "
        "chat history and database statistics. "
        "Authentication shares Django sessions."
    ),
)
FASTAPI_VERSION = os.environ.get("FASTAPI_VERSION", "1.0.0")
# Hide docs in production for security
FASTAPI_DOCS_URL = os.environ.get("FASTAPI_DOCS_URL", "/api/docs" if settings.DEBUG else None)
FASTAPI_REDOC_URL = os.environ.get("FASTAPI_REDOC_URL", "/api/redoc" if settings.DEBUG else None)
FASTAPI_OPENAPI_URL = os.environ.get(
    "FASTAPI_OPENAPI_URL", "/api/openapi.json" if settings.DEBUG else None
)

FASTAPI_CORS_ALLOW_ORIGINS = parse_env_list(
    os.environ.get("FASTAPI_CORS_ALLOW_ORIGINS"),
    [
        "https://localhost",
        "https://localhost:8443",
        "https://127.0.0.1",
        "https://127.0.0.1:8443",
    ],
)
FASTAPI_CORS_ALLOW_METHODS = parse_env_list(
    os.environ.get("FASTAPI_CORS_ALLOW_METHODS"),
    ["GET", "POST", "PUT", "PATCH", "DELETE"],
)
FASTAPI_CORS_ALLOW_HEADERS = parse_env_list(
    os.environ.get("FASTAPI_CORS_ALLOW_HEADERS"),
    ["*"],
)
FASTAPI_CORS_ALLOW_CREDENTIALS = parse_env_bool(
    os.environ.get("FASTAPI_CORS_ALLOW_CREDENTIALS"), True
)

FASTAPI_CACHE_TTL = int(os.environ.get("FASTAPI_CACHE_TTL", "30"))
FASTAPI_ROOT_TTL = int(os.environ.get("FASTAPI_ROOT_TTL", "60"))
FASTAPI_OLLAMA_CACHE_TTL = int(os.environ.get("FASTAPI_OLLAMA_CACHE_TTL", "60"))
FASTAPI_DOCKER_CACHE_TTL = int(os.environ.get("FASTAPI_DOCKER_CACHE_TTL", "60"))
FASTAPI_DOCKER_HOST = os.environ.get(
    "FASTAPI_DOCKER_HOST", "unix:///var/run/docker.sock"
)
FASTAPI_DOCKER_TIMEOUT = int(os.environ.get("FASTAPI_DOCKER_TIMEOUT", "10"))

# -------------------------
# Async Cache Helpers
# -------------------------


async def cache_get(key: str) -> Any:
    return await sync_to_async(cache.get)(key)


async def cache_set(key: str, value: Any, timeout: int = FASTAPI_CACHE_TTL) -> None:
    await sync_to_async(cache.set)(key, value, timeout)


async def cache_delete(key: str) -> None:
    await sync_to_async(cache.delete)(key)


async def cache_delete_pattern(pattern: str) -> None:
    """Delete cache entries by pattern for Redis-like backends."""
    if hasattr(cache, "delete_pattern"):
        await sync_to_async(cache.delete_pattern)(pattern)
        return

    try:
        client = getattr(cache, "client", None)
        raw_client = None

        if client is not None and hasattr(client, "get_client"):
            raw_client = client.get_client(write=True)
        elif hasattr(cache, "raw_client"):
            raw_client = cache.raw_client

        if raw_client is not None and hasattr(raw_client, "keys"):
            keys = await sync_to_async(raw_client.keys)(pattern)
            if keys:
                await sync_to_async(raw_client.delete)(*keys)
                return
    except Exception as exc:
        logger.warning("Pattern cache deletion fallback failed: %s", exc)

    logger.warning(
        "Cache backend does not support pattern deletes. "
        "Consider using django-redis for wildcard invalidation: %s",
        pattern,
    )


# -------------------------
# Cache Invalidation Helpers
# -------------------------

async def invalidate_llm_caches() -> None:
    """Invalidate all LLM-related caches when data changes."""
    patterns = [
        "fastapi_llm_list_*",
        "fastapi_llm_detail_*",
        "fastapi_llm_stats_*",
    ]
    for pattern in patterns:
        await cache_delete_pattern(pattern)


async def invalidate_user_caches(user_id: int) -> None:
    """Invalidate user-specific caches."""
    patterns = [
        f"fastapi_chat_user_{user_id}_*",
        f"fastapi_user_{user_id}_stats_*",
    ]
    for pattern in patterns:
        await cache_delete_pattern(pattern)


# -------------------------
# Service Availability Checks
# -------------------------


async def get_ollama_availability() -> bool:
    try:
        import ollama

        await sync_to_async(ollama.list)()
        return True
    except Exception as e:
        logger.debug(f"Ollama check failed: {e}")
        return False


async def get_cached_ollama_availability() -> bool:
    cache_key = "fastapi_ollama_available"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    available = await get_ollama_availability()
    await cache_set(cache_key, available, FASTAPI_OLLAMA_CACHE_TTL)
    return available


async def get_cached_api_root_payload() -> Dict[str, Any]:
    cache_key = "fastapi_api_root_payload"
    payload = await cache_get(cache_key)
    if payload is not None:
        return payload

    payload = {
        "message": FASTAPI_TITLE,
        "docs": FASTAPI_DOCS_URL,
        "version": FASTAPI_VERSION,
        "timestamp": time.time(),
    }
    await cache_set(cache_key, payload, FASTAPI_ROOT_TTL)
    return payload


async def get_cached_docker_info() -> Optional[Dict[str, Any]]:
    cache_key = "fastapi_docker_info"
    docker_info = await cache_get(cache_key)
    if docker_info is not None:
        return docker_info

    try:
        import docker

        def _docker_info():
            client = docker.DockerClient(
                base_url=FASTAPI_DOCKER_HOST,
                version="auto",
                timeout=FASTAPI_DOCKER_TIMEOUT,
            )
            return client.version()

        docker_info = await sync_to_async(_docker_info)()
    except Exception as exc:
        logger.warning("Docker unavailable from FastAPI: %s", exc)
        docker_info = None

    await cache_set(cache_key, docker_info, FASTAPI_DOCKER_CACHE_TTL)
    return docker_info


# -------------------------
# Metrics and Monitoring
# -------------------------


class Metrics:
    def __init__(self):
        self.requests_total = 0
        self.requests_by_endpoint = {}
        self.response_times = deque(maxlen=MAX_METRICS_HISTORY)
        self.errors_total = 0
        self._lock = threading.Lock()

    def record_request(self, endpoint: str, method: str, response_time: float):
        with self._lock:
            self.requests_total += 1
            key = f"{method}:{endpoint}"
            self.requests_by_endpoint[key] = self.requests_by_endpoint.get(key, 0) + 1
            self.response_times.append(response_time)

    def record_error(self):
        with self._lock:
            self.errors_total += 1

    async def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            avg_response_time = (
                sum(self.response_times) / len(self.response_times)
                if self.response_times
                else 0
            )
            return {
                "requests_total": self.requests_total,
                "requests_by_endpoint": self.requests_by_endpoint.copy(),
                "avg_response_time": round(avg_response_time, 3),
                "errors_total": self.errors_total,
            }


MAX_METRICS_HISTORY = int(os.environ.get("FASTAPI_METRICS_HISTORY", "1000"))

metrics = Metrics()


# -------------------------
# Middleware for Metrics
# -------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI starting up...")

    # Check service availability
    docker_available = await get_cached_docker_info()
    ollama_available = await get_cached_ollama_availability()

    if docker_available:
        logger.info("Docker daemon is accessible to FastAPI")
    else:
        logger.warning("Docker daemon is not accessible to FastAPI")

    if ollama_available:
        logger.info("Ollama is available")
    else:
        logger.warning("Ollama is not available on startup")

    yield

    logger.info("FastAPI shutting down...")


# -------------------------
# Exception Handlers (moved after app creation)
# -------------------------

# -------------------------
# Request/Response Middleware (moved after app creation)
# -------------------------

# -------------------------
# App Instance
# -------------------------

app = FastAPI(
    title=FASTAPI_TITLE,
    description=FASTAPI_DESCRIPTION,
    version=FASTAPI_VERSION,
    docs_url=FASTAPI_DOCS_URL,
    redoc_url=FASTAPI_REDOC_URL,
    openapi_url=FASTAPI_OPENAPI_URL,
    lifespan=lifespan,
)
app.state.limiter = limiter

# -------------------------
# Exception Handlers
# -------------------------


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    metrics.record_error()
    request_id = getattr(request.state, 'request_id', 'unknown')

    logger.warning(
        f"HTTP Exception: {exc.status_code}",
        extra={
            "request_id": request_id,
            "status_code": exc.status_code,
            "detail": exc.detail,
        }
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "type": "http_exception", "request_id": request_id},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    metrics.record_error()
    request_id = getattr(request.state, 'request_id', 'unknown')

    logger.warning(
        f"Validation Error: {len(exc.errors())} error(s)",
        extra={
            "request_id": request_id,
            "error_count": len(exc.errors()),
            "errors": str(exc.errors())[:200],  # Truncate for logging
        }
    )

    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "type": "validation_error", "request_id": request_id},
    )


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    metrics.record_error()
    request_id = getattr(request.state, 'request_id', 'unknown')
    client_ip = get_client_ip(request)

    logger.warning(
        "Rate limit exceeded",
        extra={
            "request_id": request_id,
            "client_ip": client_ip,
            "limit_detail": str(exc),
        }
    )

    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded", "type": "rate_limit", "request_id": request_id},
    )


async def general_exception_handler(request: Request, exc: Exception):
    await metrics.record_error()
    request_id = getattr(request.state, 'request_id', 'unknown')
    client_ip = get_client_ip(request)

    logger.error(
        "Unhandled exception",
        extra={
            "request_id": request_id,
            "client_ip": client_ip,
            "error_type": type(exc).__name__,
        },
        exc_info=True
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "type": "server_error",
            "request_id": request_id
        },
    )


app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_exception_handler(Exception, general_exception_handler)

# -------------------------
# Request/Response Middleware
# -------------------------


async def add_metrics_middleware(request: Request, call_next):
    start_time = time.time()
    request_id = generate_request_id()
    request.state.request_id = request_id

    # Set up request context
    client_ip = get_client_ip(request)
    structured_logger.set_request_context(request_id, ip_address=client_ip)

    try:
        response = await call_next(request)
        response_time = time.time() - start_time

        metrics.record_request(request.url.path, request.method, response_time)

        # Add response time header and request ID
        response.headers["X-Response-Time"] = f"{response_time:.3f}s"
        response.headers["X-Request-ID"] = request_id

        # Log request
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "response_time_ms": f"{response_time * 1000:.2f}",
                "client_ip": client_ip,
            }
        )

        return response
    except Exception as e:
        response_time = time.time() - start_time
        await metrics.record_request(request.url.path, request.method, response_time)

        logger.error(
            f"{request.method} {request.url.path} - Exception",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "error": str(e),
                "response_time_ms": f"{response_time * 1000:.2f}",
                "client_ip": client_ip,
            },
            exc_info=True
        )
        raise


app.middleware("http")(add_metrics_middleware)

# -------------------------
# Middleware
# -------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=FASTAPI_CORS_ALLOW_ORIGINS,
    allow_credentials=FASTAPI_CORS_ALLOW_CREDENTIALS,
    allow_methods=FASTAPI_CORS_ALLOW_METHODS,
    allow_headers=FASTAPI_CORS_ALLOW_HEADERS,
)

app.add_middleware(SlowAPIMiddleware)

# Trusted hosts for security
if not settings.DEBUG:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# -------------------------
# Routers
# -------------------------

app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM Entries"])
app.include_router(convert.router, prefix="/api/convert", tags=["Conversions"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])


# -------------------------
# API Endpoints
# -------------------------


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "FastAPI is running", "api": "/api"}


@app.get("/api", include_in_schema=False)
async def api_root():
    return JSONResponse(await get_cached_api_root_payload())


@app.get("/api/auth/verify", tags=["Auth"])
async def verify_auth(user: User = Depends(get_current_user)):
    """Verify the current Django session and return authenticated user details."""
    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "email": user.email,
    }


@app.get("/api/docker/info", tags=["Docker"])
async def docker_info():
    info = await get_cached_docker_info()
    if info is None:
        raise HTTPException(status_code=503, detail="Docker daemon unavailable")
    return info


@app.get("/api/metrics", tags=["Monitoring"])
@limiter.limit("10/minute")
async def get_metrics(request: Request):
    """Get application metrics (rate limited)."""
    return await metrics.get_stats()


@app.post("/api/cache/clear", tags=["Maintenance"])
@limiter.limit("5/minute")
async def clear_cache(request: Request):
    """Clear all cached data."""
    await sync_to_async(cache.clear)()
    return {"message": "Cache cleared successfully"}


@app.get("/api/health/detailed", tags=["Health"])
async def detailed_health():
    """Detailed health check including all services."""
    docker_info = await get_cached_docker_info()
    ollama_available = await get_cached_ollama_availability()

    return {
        "status": "healthy",
        "services": {
            "django": True,  # If we reach here, Django is working
            "database": True,  # Django setup would fail if DB is down
            "ollama": ollama_available,
            "docker": docker_info is not None,
        },
        "docker_version": docker_info.get("Version") if docker_info else None,
        "timestamp": time.time(),
    }


# -------------------------
# WebSocket Support (Optional)
# -------------------------


@app.websocket("/api/ws/chat/{user_id}")
async def websocket_chat(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time chat with session-based authentication."""
    # Validate Django session before accepting WebSocket connection
    try:
        session_key = websocket.cookies.get("sessionid")
        if not session_key:
            await websocket.close(code=4001, reason="Unauthorized: No session")
            return

        session = SessionStore(session_key=session_key)
        session_data = session.load()
        auth_user_id = session_data.get("_auth_user_id")

        if not auth_user_id or int(auth_user_id) != user_id:
            # Prevent users from connecting to other users' WebSockets
            await websocket.close(code=4003, reason="Unauthorized: User mismatch")
            logger.warning(
                f"WebSocket auth failed: requested {user_id}, authenticated {auth_user_id}"
            )
            return

        user = await sync_to_async(User.objects.get)(pk=auth_user_id)
        if not user.is_active:
            await websocket.close(code=4003, reason="Unauthorized: Account disabled")
            return

        await websocket.accept()
        logger.info(f"WebSocket connected for user {user_id}")

        try:
            while True:
                data = await websocket.receive_text()
                # Process real-time chat messages
                await websocket.send_text(f"Echo: {data}")
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket auth error: {e}", exc_info=True)
        try:
            await websocket.close(code=4000, reason="Internal server error")
        except Exception:
            pass


# -------------------------
# Lifespan and event handlers are configured in the lifespan context manager above
# @app.on_event decorators are deprecated as of FastAPI 0.93.0
# See: https://fastapi.tiangolo.com/advanced/events/
# -------------------------
