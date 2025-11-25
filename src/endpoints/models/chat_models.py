"""Pydantic models for chat history endpoints."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMessageResponse(BaseModel):
    """Response model for a single chat message."""

    id: int
    user_id: str
    session_id: Optional[str] = None
    message_type: str
    content: str
    extra_data: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    """Response model for chat history."""

    messages: List[ChatMessageResponse]
    total: int
    user_id: str
    session_id: Optional[str] = None


class ChatRequest(BaseModel):
    """Request model for sending a chat message."""

    user_id: str = Field(..., description="User identifier")
    message: str = Field(..., min_length=1, description="User message text")
    session_id: Optional[str] = Field(None, description="Optional session identifier")
    save_history: bool = Field(True, description="Whether to save message history")


class ChatResponse(BaseModel):
    """Response model for chat message."""

    response: str
    user_id: str
    session_id: Optional[str] = None


class DeleteHistoryResponse(BaseModel):
    """Response model for history deletion."""

    deleted_count: int
    user_id: str
    session_id: Optional[str] = None
