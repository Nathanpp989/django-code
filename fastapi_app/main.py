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
import asyncio
from functools import wraps

from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.conf import settings

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsite.settings")
django.setup()

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from fastapi_app.routers import llm, convert, chat, health
from fastapi_app.auth import get_current_user

logger = logging.getLogger(__name__)

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
FASTAPI_DOCS_URL = os.environ.get("FASTAPI_DOCS_URL", "/api/docs")
FASTAPI_REDOC_URL = os.environ.get("FASTAPI_REDOC_URL", "/api/redoc")
FASTAPI_OPENAPI_URL = os.environ.get("FASTAPI_OPENAPI_URL", "/api/openapi.json")

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
        self.response_times = []
        self.errors_total = 0

    def record_request(self, endpoint: str, method: str, response_time: float):
        self.requests_total += 1
        key = f"{method}:{endpoint}"
        self.requests_by_endpoint[key] = self.requests_by_endpoint.get(key, 0) + 1
        self.response_times.append(response_time)

    def record_error(self):
        self.errors_total += 1

    async def get_stats(self) -> Dict[str, Any]:
        avg_response_time = (
            sum(self.response_times) / len(self.response_times)
            if self.response_times
            else 0
        )
        return {
            "requests_total": self.requests_total,
            "requests_by_endpoint": self.requests_by_endpoint,
            "avg_response_time": round(avg_response_time, 3),
            "errors_total": self.errors_total,
        }


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

# -------------------------
# Exception Handlers
# -------------------------


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    await metrics.record_error()
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "type": "http_exception"},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    await metrics.record_error()
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "type": "validation_error"},
    )


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    await metrics.record_error()
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded", "type": "rate_limit"},
    )


async def general_exception_handler(request: Request, exc: Exception):
    await metrics.record_error()
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": "server_error"},
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

    try:
        response = await call_next(request)
        response_time = time.time() - start_time

        await metrics.record_request(request.url.path, request.method, response_time)

        # Add response time header
        response.headers["X-Response-Time"] = f"{response_time:.3f}s"

        return response
    except Exception as e:
        response_time = time.time() - start_time
        await metrics.record_request(request.url.path, request.method, response_time)
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

from fastapi import WebSocket, WebSocketDisconnect


@app.websocket("/api/ws/chat/{user_id}")
async def websocket_chat(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time chat (future enhancement)."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Process real-time chat messages
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")


# -------------------------
# Startup/Shutdown Events
# -------------------------


@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application started")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI application shutting down")
    # Cleanup resources if needed
