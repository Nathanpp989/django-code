"""
FastAPI router for NewLLM and LLMChoice REST endpoints.

Endpoints:
    GET    /api/llm/              - List all LLM entries
    POST   /api/llm/              - Create a new LLM entry
    GET    /api/llm/{id}          - Get a single LLM entry with choices
    PATCH  /api/llm/{id}          - Update an LLM entry
    DELETE /api/llm/{id}          - Delete an LLM entry
    POST   /api/llm/{id}/vote     - Vote for a choice
    GET    /api/llm/{id}/results  - Get voting results
    POST   /api/llm/{id}/choices  - Add a choice to an entry
    DELETE /api/llm/{id}/choices/{choice_id} - Delete a choice
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from django.contrib.auth.models import User
from django.db.models import Sum, F
from django.db import transaction
from typing import List, Optional
import logging
from asgiref.sync import sync_to_async

from fastapi_app.auth import get_current_user
from fastapi_app.logging_utils import (
    log_audit_trail, log_user_activity, get_client_ip, get_user_agent
)
from fastapi_app.schemas import (
    NewLLMCreate,
    NewLLMUpdate,
    LLMChoiceCreate,
    VoteRequest,
    MessageResponse,
    PaginatedResponse,
)
from django_llm.models import NewLLM, LLMChoice, LLMSummary

logger = logging.getLogger(__name__)
router = APIRouter()


# Helper functions for async DB operations
async def _create_llm_with_choices(llm_text: str, user: User, choices: List[str]) -> tuple:
    """Create LLM entry and choices atomically."""
    def _do_create():
        entry = NewLLM.objects.create(llm_text=llm_text, created_by=user)
        choice_count = 0
        if choices:
            for choice_text in choices:
                choice_text = choice_text.strip()
                if choice_text:
                    LLMChoice.objects.create(new_llm=entry, choice_text=choice_text)
                    choice_count += 1
        return entry, choice_count

    return await sync_to_async(_do_create, thread_sensitive=True)()


async def _record_vote(llm_id: int, choice_id: int) -> tuple:
    """Record a vote for a choice atomically."""
    def _do_vote():
        entry = NewLLM.objects.get(pk=llm_id)
        with transaction.atomic():
            choice = entry.choices.select_for_update().get(pk=choice_id)
            choice.amount = F("amount") + 1
            choice.save()
            choice.refresh_from_db()
        # Invalidate cache
        LLMSummary.objects.filter(content_type="results", object_id=llm_id).delete()
        return entry, choice

    return await sync_to_async(_do_vote, thread_sensitive=True)()


def serialize_llm(entry: NewLLM, include_choices: bool = False) -> dict:
    """Serialize a NewLLM instance to a dict."""
    choices = list(entry.choices.all())
    total_votes = sum(c.amount for c in choices)

    data = {
        "id": entry.pk,
        "llm_text": entry.llm_text,
        "llm_date_used": entry.llm_date_used,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "choice_count": len(choices),
        "total_votes": total_votes,
        "was_published_recently": entry.was_published_recently(),
    }

    if include_choices:
        data["choices"] = [
            {
                "id": c.pk,
                "choice_text": c.choice_text,
                "amount": c.amount,
                "created_at": c.created_at,
            }
            for c in sorted(choices, key=lambda c: c.amount, reverse=True)
        ]

    return data


# -------------------------
# List and Create
# -------------------------


@router.get(
    "/",
    response_model=PaginatedResponse,
    summary="List LLM entries",
    description="Returns a paginated list of all LLM entries.",
)
async def list_llm_entries(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Filter by text"),
    user: User = Depends(get_current_user),
):
    queryset = NewLLM.objects.prefetch_related('choices').order_by("-llm_date_used")

    if search:
        queryset = queryset.filter(llm_text__icontains=search)

    total = queryset.count()
    offset = (page - 1) * page_size
    entries = queryset[offset : offset + page_size]

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "results": [serialize_llm(e) for e in entries],
    }


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create LLM entry",
    description="Creates a new LLM entry with optional choices.",
)
async def create_llm_entry(
    payload: NewLLMCreate,
    request: Request,
    user: User = Depends(get_current_user),
):
    entry, choice_count = await _create_llm_with_choices(
        payload.llm_text, user, payload.choices
    )

    logger.info(
        f"User {user.username} created NewLLM pk={entry.pk} with {choice_count} choices",
        extra={"user_id": user.id, "llm_id": entry.pk}
    )

    # Log audit trail for create
    await log_audit_trail(
        user=user,
        action="CREATE",
        resource_type="NewLLM",
        resource_id=entry.pk,
        changes={"text_length": len(payload.llm_text), "choice_count": choice_count},
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        status="success",
    )

    # Log user activity
    await log_user_activity(
        user,
        "create_llm",
        {"llm_id": entry.pk, "choice_count": choice_count}
    )

    result = await sync_to_async(serialize_llm, thread_sensitive=True)(entry, include_choices=True)
    return result


# -------------------------
# Single entry operations
# -------------------------


@router.get(
    "/{llm_id}",
    summary="Get LLM entry",
    description="Returns a single LLM entry with all its choices.",
)
async def get_llm_entry(
    llm_id: int,
    user: User = Depends(get_current_user),
):
    try:
        entry = NewLLM.objects.prefetch_related("choices").get(pk=llm_id)
    except NewLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM entry {llm_id} not found.",
        )
    return serialize_llm(entry, include_choices=True)


@router.patch(
    "/{llm_id}",
    summary="Update LLM entry",
    description="Updates the text of an LLM entry.",
)
async def update_llm_entry(
    llm_id: int,
    payload: NewLLMUpdate,
    request: Request,
    user: User = Depends(get_current_user),
):
    try:
        entry = NewLLM.objects.get(pk=llm_id)
    except NewLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM entry {llm_id} not found.",
        )

    # Check ownership
    if entry.created_by != user:
        logger.warning(
            f"Unauthorized update attempt: user={user.username}, llm_id={llm_id}",
            extra={"user_id": user.id, "llm_id": llm_id}
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this entry.",
        )

    old_text = entry.llm_text if payload.llm_text else None

    if payload.llm_text:
        entry.llm_text = payload.llm_text
        entry.save()

    logger.info(
        f"User {user.username} updated NewLLM pk={llm_id}",
        extra={"user_id": user.id, "llm_id": llm_id}
    )

    # Log audit trail for update
    await log_audit_trail(
        user=user,
        action="UPDATE",
        resource_type="NewLLM",
        resource_id=llm_id,
        changes={
            "old_text_length": len(old_text) if old_text else None,
            "new_text_length": len(payload.llm_text) if payload.llm_text else None,
        },
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        status="success",
    )

    return serialize_llm(entry, include_choices=True)


@router.delete(
    "/{llm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete LLM entry",
    description="Deletes an LLM entry and all its choices and summaries.",
)
async def delete_llm_entry(
    llm_id: int,
    request: Request,
    user: User = Depends(get_current_user),
):
    try:
        entry = NewLLM.objects.get(pk=llm_id)
    except NewLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM entry {llm_id} not found.",
        )

    # Check ownership
    if entry.created_by != user:
        logger.warning(
            f"Unauthorized delete attempt: user={user.username}, llm_id={llm_id}",
            extra={"user_id": user.id, "llm_id": llm_id}
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this entry.",
        )

    # Store deletion info for audit log
    deleted_llm_text = entry.llm_text
    choice_count = entry.choices.count()
    summary_count = LLMSummary.objects.filter(content_type="results", object_id=llm_id).count()

    LLMSummary.objects.filter(content_type="results", object_id=llm_id).delete()
    entry.delete()

    logger.warning(
        f"User {user.username} deleted NewLLM pk={llm_id}",
        extra={"user_id": user.id, "llm_id": llm_id}
    )

    # Log audit trail for delete (compliance record)
    await log_audit_trail(
        user=user,
        action="DELETE",
        resource_type="NewLLM",
        resource_id=llm_id,
        changes={
            "text_length": len(deleted_llm_text),
            "choice_count": choice_count,
            "summary_count": summary_count,
        },
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        status="success",
    )


# -------------------------
# Voting
# -------------------------


@router.post(
    "/{llm_id}/vote",
    summary="Vote for a choice",
    description="Records a vote for a specific choice in an LLM entry.",
)
async def vote_for_choice(
    llm_id: int,
    payload: VoteRequest,
    user: User = Depends(get_current_user),
):
    try:
        entry, choice = await _record_vote(llm_id, payload.choice_id)
    except NewLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM entry {llm_id} not found.",
        )
    except LLMChoice.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Choice {payload.choice_id} not found in entry {llm_id}.",
        )

    logger.info(
        f"User {user.username} voted for choice {payload.choice_id} "
        f"in NewLLM pk={llm_id}"
    )

    return {
        "message": "Vote recorded.",
        "choice_id": choice.pk,
        "choice_text": choice.choice_text,
        "new_vote_count": choice.amount,
    }


@router.get(
    "/{llm_id}/results",
    summary="Get voting results",
    description="Returns detailed voting results for an LLM entry.",
)
async def get_voting_results(
    llm_id: int,
    user: User = Depends(get_current_user),
):
    try:
        entry = NewLLM.objects.get(pk=llm_id)
    except NewLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM entry {llm_id} not found.",
        )

    choices = entry.choices.order_by("-amount")
    total_votes = choices.aggregate(total=Sum("amount"))["total"] or 0

    return {
        "id": entry.pk,
        "llm_text": entry.llm_text,
        "total_votes": total_votes,
        "winner": choices.first().choice_text if choices.exists() else None,
        "choices": [
            {
                "id": c.pk,
                "choice_text": c.choice_text,
                "votes": c.amount,
                "percentage": round(
                    (c.amount / total_votes * 100) if total_votes > 0 else 0, 1
                ),
            }
            for c in choices
        ],
    }


# -------------------------
# Choice management
# -------------------------


@router.post(
    "/{llm_id}/choices",
    status_code=status.HTTP_201_CREATED,
    summary="Add choice",
    description="Adds a new choice to an LLM entry.",
)
async def add_choice(
    llm_id: int,
    payload: LLMChoiceCreate,
    user: User = Depends(get_current_user),
):
    try:
        entry = NewLLM.objects.get(pk=llm_id)
    except NewLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM entry {llm_id} not found.",
        )

    choice = LLMChoice.objects.create(new_llm=entry, choice_text=payload.choice_text)

    return {
        "id": choice.pk,
        "choice_text": choice.choice_text,
        "amount": choice.amount,
        "created_at": choice.created_at,
    }


@router.delete(
    "/{llm_id}/choices/{choice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete choice",
    description="Deletes a choice from an LLM entry.",
)
async def delete_choice(
    llm_id: int,
    choice_id: int,
    user: User = Depends(get_current_user),
):
    try:
        choice = LLMChoice.objects.get(pk=choice_id, new_llm_id=llm_id)
    except LLMChoice.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Choice {choice_id} not found in entry {llm_id}.",
        )
    choice.delete()
    logger.info(f"User {user.username} deleted choice {choice_id}")
