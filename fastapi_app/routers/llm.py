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

from fastapi import APIRouter, Depends, HTTPException, status, Query
from django.contrib.auth.models import User
from django.db.models import Sum, F
from django.db import transaction
from typing import List, Optional
import logging

from fastapi_app.auth import get_current_user
from fastapi_app.schemas import (
    NewLLMResponse,
    NewLLMDetailResponse,
    NewLLMCreate,
    NewLLMUpdate,
    LLMChoiceCreate,
    LLMChoiceResponse,
    VoteRequest,
    MessageResponse,
    PaginatedResponse,
)
from django_llm.models import NewLLM, LLMChoice, LLMSummary

logger = logging.getLogger(__name__)
router = APIRouter()


def serialize_llm(entry: NewLLM, include_choices: bool = False) -> dict:
    """Serialize a NewLLM instance to a dict."""
    choices = entry.choices.all()
    total_votes = choices.aggregate(total=Sum("amount"))["total"] or 0

    data = {
        "id": entry.pk,
        "llm_text": entry.llm_text,
        "llm_date_used": entry.llm_date_used,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "choice_count": choices.count(),
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
            for c in choices.order_by("-amount")
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
    queryset = NewLLM.objects.order_by("-llm_date_used")

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
    user: User = Depends(get_current_user),
):
    entry = NewLLM.objects.create(llm_text=payload.llm_text, created_by=user)

    if payload.choices:
        for choice_text in payload.choices:
            choice_text = choice_text.strip()
            if choice_text:
                LLMChoice.objects.create(new_llm=entry, choice_text=choice_text)

    logger.info(f"User {user.username} created NewLLM pk={entry.pk}")
    return serialize_llm(entry, include_choices=True)


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this entry.",
        )

    if payload.llm_text:
        entry.llm_text = payload.llm_text
        entry.save()

    logger.info(f"User {user.username} updated NewLLM pk={llm_id}")
    return serialize_llm(entry, include_choices=True)


@router.delete(
    "/{llm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete LLM entry",
    description="Deletes an LLM entry and all its choices and summaries.",
)
async def delete_llm_entry(
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

    # Check ownership
    if entry.created_by != user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this entry.",
        )

    LLMSummary.objects.filter(content_type="results", object_id=llm_id).delete()
    entry.delete()
    logger.info(f"User {user.username} deleted NewLLM pk={llm_id}")


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
        entry = NewLLM.objects.get(pk=llm_id)
    except NewLLM.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM entry {llm_id} not found.",
        )

    try:
        with transaction.atomic():
            choice = entry.choices.select_for_update().get(pk=payload.choice_id)
            choice.amount = F("amount") + 1
            choice.save()
            choice.refresh_from_db()
    except LLMChoice.DoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Choice {payload.choice_id} not found in entry {llm_id}.",
        )

    # Invalidate cached summary
    LLMSummary.objects.filter(content_type="results", object_id=llm_id).delete()

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
