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

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from django.contrib.auth.models import User
from django.db.models import Avg, Max, Min, Count
from typing import Optional
import logging

from fastapi_app.auth import get_current_user
from fastapi_app.logging_utils import (
    log_audit_trail, log_user_activity, get_client_ip, get_user_agent
)
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
    request: Request,
    user: User = Depends(get_current_user),
):
    entry = ConvertLLM.objects.create(
        new_string=payload.input_string, new_number=len(payload.input_string), created_by=user
    )
    
    logger.info(
        f"User {user.username} created ConvertLLM pk={entry.pk}",
        extra={"user_id": user.id, "convert_id": entry.pk}
    )
    
    # Log audit trail for create
    await log_audit_trail(
        user=user,
        action="CREATE",
        resource_type="ConvertLLM",
        resource_id=entry.pk,
        changes={"string_length": len(payload.input_string)},
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        status="success",
    )
    
    # Log user activity
    await log_user_activity(
        user,
        "create_llm",
        {"convert_id": entry.pk, "string_length": len(payload.input_string)}
    )
    
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
    request: Request,
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
        logger.warning(
            f"Unauthorized update attempt: user={user.username}, convert_id={convert_id}",
            extra={"user_id": user.id, "convert_id": convert_id}
        )
        
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this entry.",
        )

    old_length = entry.new_number
    entry.new_string = payload.input_string
    entry.new_number = len(payload.input_string)
    entry.save()

    # Invalidate any cached summary
    LLMSummary.objects.filter(content_type="convert", object_id=convert_id).delete()

    logger.info(
        f"User {user.username} updated ConvertLLM pk={convert_id}",
        extra={"user_id": user.id, "convert_id": convert_id}
    )
    
    # Log audit trail for update
    await log_audit_trail(
        user=user,
        action="UPDATE",
        resource_type="ConvertLLM",
        resource_id=convert_id,
        changes={"old_length": old_length, "new_length": len(payload.input_string)},
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        status="success",
    )
    
    return serialize_convert(entry)


@router.delete(
    "/{convert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete conversion",
    description="Deletes a conversion entry and its associated summaries.",
)
async def delete_conversion(
    convert_id: int,
    request: Request,
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
        logger.warning(
            f"Unauthorized delete attempt: user={user.username}, convert_id={convert_id}",
            extra={"user_id": user.id, "convert_id": convert_id}
        )
        
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this entry.",
        )

    # Store deletion info for audit log
    deleted_length = entry.new_number
    summary_count = LLMSummary.objects.filter(content_type="convert", object_id=convert_id).count()
    
    LLMSummary.objects.filter(content_type="convert", object_id=convert_id).delete()
    entry.delete()
    
    logger.warning(
        f"User {user.username} deleted ConvertLLM pk={convert_id}",
        extra={"user_id": user.id, "convert_id": convert_id}
    )
    
    # Log audit trail for delete (compliance record)
    await log_audit_trail(
        user=user,
        action="DELETE",
        resource_type="ConvertLLM",
        resource_id=convert_id,
        changes={"string_length": deleted_length, "summary_count": summary_count},
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        status="success",
    )
    logger.info(f"User {user.username} deleted ConvertLLM pk={convert_id}")
