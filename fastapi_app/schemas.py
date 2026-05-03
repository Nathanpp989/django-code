"""
Pydantic schemas for FastAPI request and response models.
These define the shape of data going in and out of the API.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
import re
import html


class LLMChoiceResponse(BaseModel):
    id: int
    choice_text: str
    amount: int
    created_at: datetime

    class Config:
        from_attributes = True


class NewLLMResponse(BaseModel):
    id: int
    llm_text: str
    llm_date_used: datetime
    created_at: datetime
    updated_at: datetime
    choice_count: int = 0
    total_votes: int = 0
    was_published_recently: bool = False

    class Config:
        from_attributes = True


class NewLLMDetailResponse(NewLLMResponse):
    choices: List[LLMChoiceResponse] = []


class NewLLMCreate(BaseModel):
    llm_text: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Text for the LLM entry"
    )
    choices: Optional[List[str]] = Field(
        default=[],
        description="Optional list of choice texts"
    )

    @validator('llm_text')
    def sanitize_llm_text(cls, v):
        if not v or not v.strip():
            raise ValueError("LLM text cannot be empty")
        # HTML escape and strip excessive whitespace
        sanitized = html.escape(v.strip())
        # Remove potential script injection attempts
        sanitized = re.sub(r'<script[^>]*>.*?</script>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)
        return sanitized[:200]  # Enforce max length

    @validator('choices')
    def validate_choices(cls, v):
        if v:
            sanitized_choices = []
            for choice in v:
                choice = choice.strip()
                if len(choice) == 0:
                    raise ValueError("Choice text cannot be empty")
                if len(choice) > 200:
                    raise ValueError("Choice text cannot exceed 200 characters")
                # Sanitize each choice
                sanitized = html.escape(choice)
                sanitized = re.sub(r'<script[^>]*>.*?</script>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)
                sanitized_choices.append(sanitized[:200])
            return sanitized_choices
        return v


class NewLLMUpdate(BaseModel):
    llm_text: Optional[str] = Field(
        None, min_length=1, max_length=200
    )

    @validator('llm_text')
    def sanitize_llm_text(cls, v):
        if v is not None:
            if not v or not v.strip():
                raise ValueError("LLM text cannot be empty")
            # HTML escape and strip excessive whitespace
            sanitized = html.escape(v.strip())
            # Remove potential script injection attempts
            sanitized = re.sub(r'<script[^>]*>.*?</script>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)
            return sanitized[:200]  # Enforce max length
        return v


class LLMChoiceCreate(BaseModel):
    choice_text: str = Field(
        ..., min_length=1, max_length=200
    )

    @validator('choice_text')
    def sanitize_choice_text(cls, v):
        if not v or not v.strip():
            raise ValueError("Choice text cannot be empty")
        # HTML escape and strip excessive whitespace
        sanitized = html.escape(v.strip())
        # Remove potential script injection attempts
        sanitized = re.sub(r'<script[^>]*>.*?</script>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)
        return sanitized[:200]  # Enforce max length


class VoteRequest(BaseModel):
    choice_id: int = Field(
        ..., description="ID of the choice to vote for"
    )


# -------------------------
# Convert LLM Schemas
# -------------------------

class ConvertLLMResponse(BaseModel):
    id: int
    new_string: str
    new_number: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConvertLLMCreate(BaseModel):
    input_string: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="String to convert and analyse"
    )


class ConvertLLMUpdate(BaseModel):
    input_string: str = Field(
        ..., min_length=1, max_length=256
    )


# -------------------------
# Chat Schemas
# -------------------------

class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Chat message to send to the LLM"
    )


# -------------------------
# Stats Schemas
# -------------------------

class DatabaseStatsResponse(BaseModel):
    llm_entries: int
    total_choices: int
    total_votes: int
    convert_entries: int
    chat_messages: int
    llm_summaries: int


# -------------------------
# Pagination Schema
# -------------------------

class PaginatedResponse(BaseModel):
    count: int
    page: int
    page_size: int
    total_pages: int
    results: list


# -------------------------
# Generic Responses
# -------------------------

class MessageResponse(BaseModel):
    message: str
    status: str = "success"


class ErrorResponse(BaseModel):
    detail: str
