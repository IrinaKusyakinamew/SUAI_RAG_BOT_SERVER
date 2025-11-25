"""Data Access Object for chat history operations."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.chat_history import ChatHistory
from db.session import get_current_session
from db.transaction import transactional


class ChatHistoryDAO:
    """DAO for managing chat history in the database."""

    @staticmethod
    @transactional
    async def save_message(
        user_id: str,
        message_type: str,
        content: str,
        session_id: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> ChatHistory:
        """
        Save a chat message to the database.

        Args:
            user_id: User identifier (Telegram ID or other)
            message_type: Type of message ('user' or 'assistant')
            content: Message text
            session_id: Optional session identifier
            extra_data: Optional additional metadata

        Returns:
            Created ChatHistory object
        """
        session = get_current_session()

        chat_message = ChatHistory(
            user_id=user_id,
            message_type=message_type,
            content=content,
            session_id=session_id,
            extra_data=extra_data,
        )

        session.add(chat_message)
        await session.flush()
        await session.refresh(chat_message)

        return chat_message

    @staticmethod
    async def get_user_history(
        user_id: str,
        limit: int = 50,
        session_id: Optional[str] = None,
    ) -> List[ChatHistory]:
        """
        Get chat history for a specific user.

        Args:
            user_id: User identifier
            limit: Maximum number of messages to retrieve
            session_id: Optional session filter

        Returns:
            List of ChatHistory objects ordered by creation time
        """
        session = get_current_session()

        query = select(ChatHistory).where(ChatHistory.user_id == user_id)

        # if session_id:
        #     query = query.where(ChatHistory.session_id == session_id)

        query = query.order_by(ChatHistory.created_at.desc()).limit(limit)

        result = await session.execute(query)
        messages = result.scalars().all()

        # Return in chronological order (oldest first)
        return list(reversed(messages))

    @staticmethod
    async def get_recent_context(
        user_id: str,
        limit: int = 10,
        session_id: Optional[str] = None,
    ) -> List[dict]:
        """
        Get recent chat context formatted for AI models.

        Args:
            user_id: User identifier
            limit: Maximum number of messages
            session_id: Optional session filter

        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        messages = await ChatHistoryDAO.get_user_history(
            user_id=user_id,
            limit=limit,
            session_id=session_id,
        )

        return [
            {
                "role": "user" if msg.message_type == "user" else "assistant",
                "content": msg.content,
            }
            for msg in messages
        ]

    @staticmethod
    @transactional
    async def delete_user_history(
        user_id: str,
        session_id: Optional[str] = None,
    ) -> int:
        """
        Delete chat history for a user.

        Args:
            user_id: User identifier
            session_id: Optional session filter (if None, deletes all user history)

        Returns:
            Number of deleted messages
        """
        session = get_current_session()

        query = select(ChatHistory).where(ChatHistory.user_id == user_id)

        if session_id:
            query = query.where(ChatHistory.session_id == session_id)

        result = await session.execute(query)
        messages = result.scalars().all()

        count = len(messages)
        for message in messages:
            await session.delete(message)

        return count

    @staticmethod
    async def get_session_history(
        session_id: str,
        limit: int = 100,
    ) -> List[ChatHistory]:
        """
        Get all messages from a specific session.

        Args:
            session_id: Session identifier
            limit: Maximum number of messages

        Returns:
            List of ChatHistory objects ordered by creation time
        """
        session = get_current_session()

        query = (
            select(ChatHistory)
            .where(ChatHistory.session_id == session_id)
            .order_by(ChatHistory.created_at.asc())
            .limit(limit)
        )

        result = await session.execute(query)
        return list(result.scalars().all())


# Global DAO instance
chat_history_dao = ChatHistoryDAO()
