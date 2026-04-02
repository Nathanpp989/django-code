"""
FastAPI router for Chat REST endpoints.

Endpoints:
    GET    /api/chat/          - Get chat history for current user
    POST   /api/chat/          - Send a message and get a response
    DELETE /api/chat/          - Clear chat history
    GET    /api/chat/stats     - Get chat statistics
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from django.contrib.auth.models import User
from django.db.models import Count
from typing import List
import logging

from fastapi_app.auth import get_current_user
from fastapi_app.schemas import (
    ChatMessageResponse,
    ChatMessageCreate,
    MessageResponse,
    PaginatedResponse,
)
from django_llm.models import ChatMessage, ReverseLLM

logger = logging.getLogger(__name__)
router = APIRouter()

# Import Ollama and MCP client safely
try:
    from django_llm.mcp_client import MCPOllamaClient, OLLAMA_AVAILABLE
    from django_llm.prompts import CHAT_SYSTEM_PROMPT

    mcp_client = MCPOllamaClient()
except Exception as e:
    logger.warning(f"MCP client unavailable: {e}")
    mcp_client = None
    OLLAMA_AVAILABLE = False
    CHAT_SYSTEM_PROMPT = ""


def serialize_message(msg: ChatMessage) -> dict:
    return {
        "id": msg.pk,
        "role": msg.role,
        "content": msg.content,
        "created_at": msg.created_at,
    }


# -------------------------
# Stats endpoint
# -------------------------


@router.get(
    "/stats",
    summary="Chat statistics",
    description="Returns statistics about the current user's chat history.",
)
async def get_chat_stats(
    user: User = Depends(get_current_user),
):
    stats = ChatMessage.objects.filter(user=user).aggregate(
        total=Count("id"),
        user_messages=Count(
            "id", filter=__import__("django.db.models", fromlist=["Q"]).Q(role="user")
        ),
        assistant_messages=Count(
            "id",
            filter=__import__("django.db.models", fromlist=["Q"]).Q(role="assistant"),
        ),
    )
    return {
        "total_messages": stats["total"] or 0,
        "user_messages": stats["user_messages"] or 0,
        "assistant_messages": stats["assistant_messages"] or 0,
        "ollama_available": OLLAMA_AVAILABLE,
    }


# -------------------------
# List chat history
# -------------------------


@router.get(
    "/",
    response_model=PaginatedResponse,
    summary="Get chat history",
    description="Returns paginated chat history for the current user.",
)
async def get_chat_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    queryset = ChatMessage.objects.filter(user=user).order_by("created_at")

    total = queryset.count()
    offset = (page - 1) * page_size
    messages = queryset[offset : offset + page_size]

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "results": [serialize_message(m) for m in messages],
    }


# -------------------------
# Send message
# -------------------------


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Send chat message",
    description=(
        "Sends a message to the LLM and returns the response. "
        "Saves both messages to the chat history. "
        "Uses MCP tools to query the database if relevant."
    ),
)
async def send_chat_message(
    payload: ChatMessageCreate,
    user: User = Depends(get_current_user),
):
    if not OLLAMA_AVAILABLE or mcp_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama is not available. Start it with: ollama serve",
        )

    # Save user message
    ChatMessage.objects.create(user=user, role="user", content=payload.message)

    # Build conversation history
    history = (
        ChatMessage.objects.filter(user=user)
        .order_by("created_at")
        .values("role", "content")
    )

    ollama_messages = [
        {"role": msg["role"], "content": msg["content"]} for msg in history
    ]

    # Get AI response
    try:
        ai_response = mcp_client.chat_with_tools_and_history(
            messages=ollama_messages,
            system=CHAT_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.error(f"Chat API error for user {user.username}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM error: {str(e)}",
        )

    # Save AI response
    ai_message = ChatMessage.objects.create(
        user=user, role="assistant", content=ai_response
    )

    return {
        "user_message": payload.message,
        "ai_response": ai_response,
        "message_id": ai_message.pk,
        "created_at": ai_message.created_at,
    }


# -------------------------
# Clear chat history
# -------------------------


@router.delete(
    "/",
    summary="Clear chat history",
    description="Deletes all chat messages for the current user.",
)
async def clear_chat_history(
    user: User = Depends(get_current_user),
):
    deleted_count, _ = ChatMessage.objects.filter(user=user).delete()
    logger.info(f"API cleared {deleted_count} messages for user {user.username}")
    return {"message": f"Cleared {deleted_count} messages.", "status": "success"}
