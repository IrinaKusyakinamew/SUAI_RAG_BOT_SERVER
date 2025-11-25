"""API endpoints for SGR Agent."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.agent_config import GlobalConfig
from core.agent_definition import AgentDefinition
from core.agent_factory import AgentFactory
from core.agents.sgr_agent import SGRAgent
from core.base_agent import BaseAgent
from core.models import AgentStatesEnum
from core.tools import FinalAnswerTool, ReasoningTool, WebSearchTool
from endpoints.models.agent_models import (
    AgentListItem,
    AgentListResponse,
    AgentStateResponse,
    ChatCompletionRequest,
    ClarificationRequest,
    HealthResponse,
)
from utils.config import CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Storage for active agents
agents_storage: dict[str, BaseAgent] = {}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse()


@router.get("/agents/{agent_id}/state", response_model=AgentStateResponse)
async def get_agent_state(agent_id: str):
    """Get current state of an agent."""
    if agent_id not in agents_storage:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent = agents_storage[agent_id]

    return AgentStateResponse(
        agent_id=agent.id,
        task=agent.task,
        sources_count=len(agent._context.sources),
        **agent._context.model_dump(),
    )


@router.get("/agents", response_model=AgentListResponse)
async def get_agents_list():
    """Get list of all active agents."""
    agents_list = [
        AgentListItem(
            agent_id=agent.id,
            task=agent.task,
            state=agent._context.state,
            creation_time=agent.creation_time,
        )
        for agent in agents_storage.values()
    ]

    return AgentListResponse(agents=agents_list, total=len(agents_list))


@router.get("/v1/models")
async def get_available_models():
    """Get a list of available agent models."""
    # Return default SGR agent
    models_data = [
        {
            "id": "sgr_agent",
            "object": "model",
            "created": 1234567890,
            "owned_by": "rag-server",
        }
    ]

    return {"data": models_data, "object": "list"}


def extract_user_content_from_messages(messages):
    """Extract user content from messages list."""
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    raise ValueError("User message not found in messages")


@router.post("/agents/{agent_id}/provide_clarification")
async def provide_clarification(agent_id: str, request: ClarificationRequest):
    """Provide clarification to an agent waiting for user input."""
    try:
        agent = agents_storage.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        logger.info(f"Providing clarification to agent {agent.id}: {request.clarifications[:100]}...")

        await agent.provide_clarification(request.clarifications)
        return StreamingResponse(
            agent.streaming_generator.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Agent-ID": str(agent.id),
            },
        )

    except Exception as e:
        logger.error(f"Error providing clarification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _is_agent_id(model_str: str) -> bool:
    """Check if the model string is an agent ID (contains underscore and UUID-like format)."""
    return "_" in model_str and len(model_str) > 20


async def _create_agent_definition(model_name: str) -> AgentDefinition:
    """Create agent definition with appropriate tools."""
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
        logger.info("WebSearchTool enabled for agent")

    # Prepare search config as dict or None
    search_dict = None
    if has_search_api:
        search_dict = config.search.model_dump()

    agent_def = AgentDefinition(
        name=model_name,
        base_class=SGRAgent,
        tools=tools,
        search=search_dict,
    )

    return agent_def


@router.post("/v1/chat/completions")
async def create_chat_completion(request: ChatCompletionRequest):
    """
    OpenAI-compatible chat completion endpoint.
    Supports streaming mode only.
    """
    if not request.stream:
        raise HTTPException(status_code=501, detail="Only streaming responses are supported. Set 'stream=true'")

    # Check if this is a clarification request for an existing agent
    if (
        request.model
        and isinstance(request.model, str)
        and _is_agent_id(request.model)
        and request.model in agents_storage
        and agents_storage[request.model]._context.state == AgentStatesEnum.WAITING_FOR_CLARIFICATION
    ):
        return await provide_clarification(
            agent_id=request.model,
            request=ClarificationRequest(clarifications=extract_user_content_from_messages(request.messages)),
        )

    try:
        task = extract_user_content_from_messages(request.messages)

        # Create agent definition
        agent_def = await _create_agent_definition(request.model or "sgr_agent")

        # Create agent
        agent = await AgentFactory.create(agent_def, task)
        logger.info(f"Created agent '{request.model}' for task: {task[:100]}...")

        agents_storage[agent.id] = agent

        # Start agent execution in background
        _ = asyncio.create_task(agent.execute())

        return StreamingResponse(
            agent.streaming_generator.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Agent-ID": str(agent.id),
                "X-Agent-Model": request.model or "sgr_agent",
            },
        )

    except ValueError as e:
        logger.error(f"Error in chat completion: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in chat completion: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
