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


class FinalAnswerTool(BaseTool):
    """Finalize a research task and complete agent execution after all steps
    are completed.

    Usage: Call after you complete a research task
    """

    reasoning: str = Field(description="Why task is now complete and how answer was verified")
    completed_steps: list[str] = Field(
        description="Summary of completed steps including verification", min_length=1, max_length=5
    )
    answer: str = Field(description="Comprehensive final answer with EXACT factual details (dates, numbers, names)")
    status: Literal[AgentStatesEnum.COMPLETED, AgentStatesEnum.FAILED] = Field(description="Task completion status")

    async def __call__(self, context: ResearchContext, config: AgentConfig, **_) -> str:
        context.state = self.status
        context.execution_result = self.answer
        return self.model_dump_json(
            indent=2,
        )
