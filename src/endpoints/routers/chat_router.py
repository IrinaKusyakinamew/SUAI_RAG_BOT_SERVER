"""API endpoints for chat and chat history."""

import hashlib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from core.service import agent_service
from dao.chat_history_dao import chat_history_dao
from db.session import set_db_session_context
from endpoints.models.chat_models import (
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    DeleteHistoryResponse,
)
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/message", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """
    Send a message to the agent and get a response.
    History is automatically saved to the database.
    """
    # Set up database session context
    session_context_id = int(
        hashlib.sha256(f"{request.user_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:8],
        16,
    )
    set_db_session_context(session_id=session_context_id)

    try:
        logger.info(f"Processing message from user {request.user_id}")

        response = await agent_service.process_message(
            user_id=request.user_id,
            message=request.message,
            session_id=request.session_id,
            save_history=request.save_history,
        )

        return ChatResponse(
            response=response,
            user_id=request.user_id,
            session_id=request.session_id,
        )

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_db_session_context(session_id=None)


@router.get("/history/{user_id}", response_model=ChatHistoryResponse)
async def get_user_history(
    user_id: str,
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of messages to return"),
):
    """
    Get chat history for a specific user.
    Optionally filter by session_id.
    """
    # Set up database session context
    session_context_id = int(
        hashlib.sha256(f"history_{user_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:8],
        16,
    )
    set_db_session_context(session_id=session_context_id)

    try:
        logger.info(f"Fetching history for user {user_id}")

        messages = await chat_history_dao.get_user_history(
            user_id=user_id,
            limit=limit,
            session_id=session_id,
        )

        message_responses = [
            ChatMessageResponse(
                id=msg.id,
                user_id=msg.user_id,
                session_id=msg.session_id,
                message_type=msg.message_type,
                content=msg.content,
                extra_data=msg.extra_data,
                created_at=msg.created_at,
            )
            for msg in messages
        ]

        return ChatHistoryResponse(
            messages=message_responses,
            total=len(message_responses),
            user_id=user_id,
            session_id=session_id,
        )

    except Exception as e:
        logger.error(f"Error fetching history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_db_session_context(session_id=None)


@router.get("/history/session/{session_id}", response_model=ChatHistoryResponse)
async def get_session_history(
    session_id: str,
    limit: int = Query(100, ge=1, le=500, description="Maximum number of messages to return"),
):
    """Get all messages from a specific session."""
    # Set up database session context
    session_context_id = int(
        hashlib.sha256(f"session_{session_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:8],
        16,
    )
    set_db_session_context(session_id=session_context_id)

    try:
        logger.info(f"Fetching history for session {session_id}")

        messages = await chat_history_dao.get_session_history(
            session_id=session_id,
            limit=limit,
        )

        message_responses = [
            ChatMessageResponse(
                id=msg.id,
                user_id=msg.user_id,
                session_id=msg.session_id,
                message_type=msg.message_type,
                content=msg.content,
                extra_data=msg.extra_data,
                created_at=msg.created_at,
            )
            for msg in messages
        ]

        return ChatHistoryResponse(
            messages=message_responses,
            total=len(message_responses),
            user_id=messages[0].user_id if messages else "",
            session_id=session_id,
        )

    except Exception as e:
        logger.error(f"Error fetching session history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_db_session_context(session_id=None)


@router.delete("/history/{user_id}", response_model=DeleteHistoryResponse)
async def delete_user_history(
    user_id: str,
    session_id: Optional[str] = Query(None, description="Delete only specific session (if provided)"),
):
    """
    Delete chat history for a user.
    If session_id is provided, only that session is deleted.
    Otherwise, all user history is deleted.
    """
    # Set up database session context
    session_context_id = int(
        hashlib.sha256(f"delete_{user_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:8],
        16,
    )
    set_db_session_context(session_id=session_context_id)

    try:
        logger.info(f"Deleting history for user {user_id}, session: {session_id}")

        deleted_count = await chat_history_dao.delete_user_history(
            user_id=user_id,
            session_id=session_id,
        )

        return DeleteHistoryResponse(
            deleted_count=deleted_count,
            user_id=user_id,
            session_id=session_id,
        )

    except Exception as e:
        logger.error(f"Error deleting history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_db_session_context(session_id=None)
