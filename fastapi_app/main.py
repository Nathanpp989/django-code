"""
FastAPI application for Django LLM REST API.

Runs alongside Django on port 8001.
NGINX routes /api/ requests here.

Shares Django's database and session authentication.

Start with:
    uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8001 --reload

Or via the Makefile:
    make fastapi
"""

import os
import sys
import django
from pathlib import Path

# -------------------------
# Django setup
# Must happen before importing Django models
# -------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsite.settings")
django.setup()

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from contextlib import asynccontextmanager
import logging

from fastapi_app.routers import llm, convert, chat, health
from fastapi_app.auth import get_current_user

logger = logging.getLogger(__name__)


# -------------------------
# Lifespan
# Runs on startup and shutdown
# -------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI starting up...")
    try:
        import ollama

        ollama.list()
        logger.info("Ollama is available")
    except Exception:
        logger.warning("Ollama is not available on startup")
    yield
    logger.info("FastAPI shutting down...")


# -------------------------
# App instance
# -------------------------
app = FastAPI(
    title="Django LLM API",
    description=(
        "REST API for the Django LLM project. "
        "Provides access to LLM entries, conversions, "
        "chat history and database statistics. "
        "Authentication shares Django sessions."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# -------------------------
# CORS
# Allows the Django frontend to call the API
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://localhost",
        "https://localhost:8443",
        "https://127.0.0.1",
        "https://127.0.0.1:8443",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# -------------------------
# Routers
# Each router handles a group of endpoints
# -------------------------
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(llm.router, prefix="/api/llm", tags=["LLM Entries"])
app.include_router(convert.router, prefix="/api/convert", tags=["Conversions"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])


# -------------------------
# Root redirect
# -------------------------
@app.get("/api", include_in_schema=False)
async def api_root():
    return JSONResponse(
        {
            "message": "Django LLM API",
            "docs": "/api/docs",
            "version": "1.0.0",
        }
    )
