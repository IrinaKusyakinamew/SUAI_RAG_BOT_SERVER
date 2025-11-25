from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from core.base_tool import BaseTool
from core.models import AgentStatesEnum
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.agent_definition import AgentConfig
    from core.models import ResearchContext

logger = get_logger(__name__)


class OutOfDomainTool(BaseTool):

    answer: str = Field(description="Please reply that the request is dangerous or not related to the bot's topic.")

    async def __call__(self, context: ResearchContext, config: AgentConfig, **_) -> str:
        context.state = AgentStatesEnum.FAILED
        context.execution_result = self.answer
        return self.model_dump_json(
            indent=2,
        )
