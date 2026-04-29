"""
FastAPI router for ConvertLLM REST endpoints.

Endpoints:
    GET    /api/convert/       - List all conversions
    POST   /api/convert/       - Create a new conversion
    GET    /api/convert/{id}   - Get a single conversion
    PATCH  /api/convert/{id}   - Update a conversion
    DELETE /api/convert/{id}   - Delete a conversion
    GET    /api/convert/stats  - Get conversion statistics
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from django.contrib.auth.models import User
from django.db.models import Avg, Max, Min, Count
from typing import Optional
import logging

from fastapi_app.auth import get_current_user
from fastapi_app.schemas import (
    ConvertLLMResponse,
    ConvertLLMCreate,
    ConvertLLMUpdate,
    PaginatedResponse,
)
from django_llm.models import ConvertLLM, LLMSummary

logger = logging.getLogger(__name__)
router = APIRouter()


def serialize_convert(entry: ConvertLLM) -> dict:
    """Serialize a ConvertLLM instance to a dict."""
    return {
        "id": entry.pk,
        "new_string": entry.new_string,
        "new_number": entry.new_number,
        "word_count": len(entry.new_string.split()) if entry.new_string else 0,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


# -------------------------
# Stats endpoint
# Must be before /{id} to avoid routing conflict
# -------------------------


@router.get(
    "/stats",
    summary="Conversion statistics",
    description="Returns aggregate statistics about all conversions.",
)
async def get_conversion_stats(
    user: User = Depends(get_current_user),
):
    stats = ConvertLLM.objects.aggregate(
        total=Count("id"),
        avg_length=Avg("new_number"),
        max_length=Max("new_number"),
        min_length=Min("new_number"),
    )
    return {
        "total_conversions": stats["total"] or 0,
        "average_character_count": round(stats["avg_length"] or 0, 1),
        "max_character_count": stats["max_length"] or 0,
        "min_character_count": stats["min_length"] or 0,
    }


# -------------------------
# List and Create
# -------------------------


@router.get(
    "/",
    response_model=PaginatedResponse,
    summary="List conversions",
    description="Returns a paginated list of all string conversions.",
)
async def list_conversions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Filter by string content"),
    user: User = Depends(get_current_user),
):
    queryset = ConvertLLM.objects.order_by("-created_at")

    if search:
        queryset = queryset.filter(new_string__icontains=search)

    total = queryset.count()
    offset = (page - 1) * page_size
    entries = queryset[offset : offset + page_size]

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "results": [serialize_convert(e) for e in entries],
    }


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create conversion",
    description="Creates a new string conversion entry.",
)
async def create_conversion(
    payload: ConvertLLMCreate,
    user: User = Depends(get_current_user),
):
    entry = ConvertLLM.objects.create(
        new_string=payload.input_string, new_number=len(payload.input_string), created_by=user
    )
    logger.info(f"User {user.username} created ConvertLLM pk={entry.pk}")
    return serialize_convert(entry)


# -------------------------
# Single entry operations
# -------------------------


@router.get(
    "/{convert_id}",
    summary="Get conversion",
    description="Returns a single conversion entry.",
)
async def get_conversion(
    convert_id: int,
    user: User = Depends(get_current_user),
):
    try:
        entry = ConvertLLM.objects.get(pk=convert_id)
    except ConvertLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversion {convert_id} not found.",
        )
    return serialize_convert(entry)


@router.patch(
    "/{convert_id}",
    summary="Update conversion",
    description="Updates the string content of a conversion entry.",
)
async def update_conversion(
    convert_id: int,
    payload: ConvertLLMUpdate,
    user: User = Depends(get_current_user),
):
    try:
        entry = ConvertLLM.objects.get(pk=convert_id)
    except ConvertLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversion {convert_id} not found.",
        )

    # Check ownership
    if entry.created_by != user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this entry.",
        )

    entry.new_string = payload.input_string
    entry.new_number = len(payload.input_string)
    entry.save()

    # Invalidate any cached summary
    LLMSummary.objects.filter(content_type="convert", object_id=convert_id).delete()

    logger.info(f"User {user.username} updated ConvertLLM pk={convert_id}")
    return serialize_convert(entry)


@router.delete(
    "/{convert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete conversion",
    description="Deletes a conversion entry and its associated summaries.",
)
async def delete_conversion(
    convert_id: int,
    user: User = Depends(get_current_user),
):
    try:
        entry = ConvertLLM.objects.get(pk=convert_id)
    except ConvertLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversion {convert_id} not found.",
        )

    # Check ownership
    if entry.created_by != user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this entry.",
        )

    LLMSummary.objects.filter(content_type="convert", object_id=convert_id).delete()
    entry.delete()
    logger.info(f"User {user.username} deleted ConvertLLM pk={convert_id}")
