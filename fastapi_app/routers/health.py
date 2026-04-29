"""
Health check endpoints for FastAPI.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from django.db import connection
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/health",
    summary="Health check",
    description="Returns the status of FastAPI, Django database and Ollama."
)
async def health_check():
    status = {
        "fastapi": "ok",
        "database": "ok",
        "ollama": "unavailable",
    }

    # Check database
    try:
        connection.ensure_connection()
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {str(e)}"
        logger.error(f"Health check DB error: {e}")

    # Check Ollama
    try:
        import ollama
        await asyncio.to_thread(ollama.list)
        status["ollama"] = "ok"
    except Exception:
        status["ollama"] = "unavailable"

    http_status = 200 if status["database"] == "ok" else 500
    return JSONResponse(status, status_code=http_status)
