"""Agent service for processing user messages using SGR Agent."""

import hashlib
from datetime import datetime
from typing import Dict, Optional

from core import OutOfDomainTool
from core.agent_config import GlobalConfig
from core.agent_definition import AgentDefinition
from core.agent_factory import AgentFactory
from core.agents.sgr_agent import SGRAgent
from core.tools import (
    ClarificationTool,
    FinalAnswerTool,
    ReasoningTool,
    WebSearchTool,
)
from dao.chat_history_dao import chat_history_dao
from db.session import set_db_session_context
from utils.config import CONFIG
from utils.logger import get_logger

log = get_logger("AgentService")


class AgentService:
    """Service for managing and running SGR agents."""

    def __init__(self):
        self.agents: Dict[str, object] = {}
        log.info("AgentService initialized")

    async def process_message(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        save_history: bool = True,
    ) -> str:
        """
        Process a user message using SGR Agent.

        Args:
            user_id: Unique user identifier
            message: User message text
            session_id: Optional session identifier for grouping messages
            save_history: Whether to save message history to database

        Returns:
            Agent response text
        """
        # Set up database session context
        session_context_id = int(hashlib.sha256(f"{user_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:8], 16)
        set_db_session_context(session_id=session_context_id)

        try:
            log.info(f"Processing message from user {user_id}: {message[:50]}...")

            # Get conversation history (last 10 messages = 5 Q&A pairs) before saving new message
            conversation_history = []
            if session_id:
                try:
                    # Get last 10 messages (not including the current one)
                    history = await chat_history_dao.get_recent_context(
                        user_id=user_id,
                        limit=10,
                        session_id=session_id,
                    )
                    conversation_history = history
                    log.debug(f"Loaded {len(conversation_history)} messages from history")
                except Exception as e:
                    log.error(f"Failed to load conversation history: {e}", exc_info=True)

            # Save user message to history
            if save_history:
                try:
                    log.info(f"Saving user message with session_id={session_id}")
                    saved_msg = await chat_history_dao.save_message(
                        user_id=user_id,
                        message_type="user",
                        content=message,
                        session_id=session_id,
                    )
                    log.info(f"✅ User message saved: ID={saved_msg.id}, session_id={saved_msg.session_id}")
                except Exception as e:
                    log.error(f"❌ Failed to save user message to history: {e}", exc_info=True)

            # Initialize GlobalConfig
            config = GlobalConfig()

            # Determine if search is available
            has_search_api = config.search and config.search.tavily_api_key

            # Create agent definition with tools
            tools = [
                ReasoningTool,
                FinalAnswerTool,
                OutOfDomainTool,
            ]

            # Add WebSearchTool only if Tavily API key is configured
            if has_search_api:
                tools.append(WebSearchTool)
                log.info("WebSearchTool enabled (Tavily API key found)")
            else:
                log.info("WebSearchTool disabled (no Tavily API key)")

            # Prepare search config as dict or None
            search_dict = None
            if has_search_api:
                search_dict = config.search.model_dump()

            agent_def = AgentDefinition(
                name="sgr_agent",
                base_class=SGRAgent,
                tools=tools,
                search=search_dict,  # Pass dict or None
            )

            # Create agent using factory with conversation history
            agent = await AgentFactory.create(
                agent_def=agent_def,
                task=message,
                conversation_history=conversation_history,
            )

            # Run agent
            await agent.execute()

            log.info(f"Agent completed for user {user_id}")

            # Extract final answer from agent context
            result = agent._context.execution_result
            response_text = ""
            if result and hasattr(result, "final_answer"):
                response_text = result.final_answer
            elif result:
                response_text = str(result)
            else:
                response_text = "Агент завершил работу, но не предоставил ответ."

            # Save assistant response to history
            if save_history and response_text:
                try:
                    log.info(f"Saving assistant response with session_id={session_id}")
                    saved_msg = await chat_history_dao.save_message(
                        user_id=user_id,
                        message_type="assistant",
                        content=response_text,
                        session_id=session_id,
                    )
                    log.info(f"✅ Assistant response saved: ID={saved_msg.id}, session_id={saved_msg.session_id}")
                except Exception as e:
                    log.error(f"❌ Failed to save assistant response to history: {e}", exc_info=True)

            return response_text

        except Exception as e:
            log.error(f"Error processing message for user {user_id}: {e}", exc_info=True)
            error_response = f"Извините, произошла ошибка при обработке вашего запроса: {str(e)}"

            # Try to save error response to history
            if save_history:
                try:
                    await chat_history_dao.save_message(
                        user_id=user_id,
                        message_type="assistant",
                        content=error_response,
                        session_id=session_id,
                        extra_data={"error": True, "error_message": str(e)},
                    )
                except Exception as save_error:
                    log.error(f"Failed to save error response to history: {save_error}")

            return error_response
        finally:
            # Clear session context
            set_db_session_context(session_id=None)


# Global agent service instance
agent_service = AgentService()
