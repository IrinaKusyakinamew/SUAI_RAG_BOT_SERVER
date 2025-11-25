"""Agent service for processing user messages using SGR Agent."""

from typing import Dict

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
from utils.config import CONFIG
from utils.logger import get_logger

log = get_logger("AgentService")


class AgentService:
    """Service for managing and running SGR agents."""

    def __init__(self):
        self.agents: Dict[str, object] = {}
        log.info("AgentService initialized")

    async def process_message(self, user_id: str, message: str) -> str:
        """
        Process a user message using SGR Agent.

        Args:
            user_id: Unique user identifier
            message: User message text

        Returns:
            Agent response text
        """
        try:
            log.info(f"Processing message from user {user_id}: {message[:50]}...")

            # Initialize GlobalConfig
            config = GlobalConfig()

            # Determine if search is available
            has_search_api = config.search and config.search.tavily_api_key

            # Create agent definition with tools
            tools = [
                ReasoningTool,
                FinalAnswerTool,
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

            # Create agent using factory
            agent = await AgentFactory.create(agent_def=agent_def, task=message)

            # Run agent
            await agent.execute()

            log.info(f"Agent completed for user {user_id}")

            # Extract final answer from agent context
            result = agent._context.execution_result
            if result and hasattr(result, "final_answer"):
                return result.final_answer
            elif result:
                return str(result)
            else:
                return "Агент завершил работу, но не предоставил ответ."

        except Exception as e:
            log.error(f"Error processing message for user {user_id}: {e}", exc_info=True)
            return f"Извините, произошла ошибка при обработке вашего запроса: {str(e)}"


# Global agent service instance
agent_service = AgentService()
