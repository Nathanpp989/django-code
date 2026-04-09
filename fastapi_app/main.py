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

from asgiref.sync import sync_to_async
from django.core.cache import cache

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsite.settings")
django.setup()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fastapi_app.routers import llm, convert, chat, health
from fastapi_app.auth import get_current_user

logger = logging.getLogger(__name__)


def parse_env_list(value, default):
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_env_bool(value, default=False):
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


async def cache_get(key):
    return await sync_to_async(cache.get)(key)


async def cache_set(key, value, timeout=FASTAPI_CACHE_TTL):
    await sync_to_async(cache.set)(key, value, timeout)


async def get_ollama_availability() -> bool:
    try:
        import ollama
        ollama.list()
        return True
    except Exception:
        return False


async def get_cached_ollama_availability() -> bool:
    cache_key = "fastapi_ollama_available"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    available = await get_ollama_availability()
    await cache_set(cache_key, available, FASTAPI_OLLAMA_CACHE_TTL)
    return available


async def get_cached_api_root_payload():
    cache_key = "fastapi_api_root_payload"
    payload = await cache_get(cache_key)
    if payload is not None:
        return payload

    payload = {
        "message": FASTAPI_TITLE,
        "docs": FASTAPI_DOCS_URL,
        "version": FASTAPI_VERSION,
    }
    await cache_set(cache_key, payload, FASTAPI_ROOT_TTL)
    return payload


async def get_cached_docker_info():
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI starting up...")
    if await get_cached_docker_info():
        logger.info("Docker daemon is accessible to FastAPI")
    else:
        logger.warning("Docker daemon is not accessible to FastAPI")

    if await get_cached_ollama_availability():
        logger.info("Ollama is available")
    else:
        logger.warning("Ollama is not available on startup")
    yield
    logger.info("FastAPI shutting down...")


app = FastAPI(
    title=FASTAPI_TITLE,
    description=FASTAPI_DESCRIPTION,
    version=FASTAPI_VERSION,
    docs_url=FASTAPI_DOCS_URL,
    redoc_url=FASTAPI_REDOC_URL,
    openapi_url=FASTAPI_OPENAPI_URL,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FASTAPI_CORS_ALLOW_ORIGINS,
    allow_credentials=FASTAPI_CORS_ALLOW_CREDENTIALS,
    allow_methods=FASTAPI_CORS_ALLOW_METHODS,
    allow_headers=FASTAPI_CORS_ALLOW_HEADERS,
)

app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM Entries"])
app.include_router(convert.router, prefix="/api/convert", tags=["Conversions"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])


@app.get("/api", include_in_schema=False)
async def api_root():
    return JSONResponse(await get_cached_api_root_payload())


@app.get("/api/docker/info", tags=["Docker"])
async def docker_info():
    info = await get_cached_docker_info()
    if info is None:
        raise HTTPException(status_code=503, detail="Docker daemon unavailable")
    return info
