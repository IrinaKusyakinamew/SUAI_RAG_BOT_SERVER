from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, ClassVar

from fastmcp import Client
from pydantic import BaseModel

from core.agent_config import GlobalConfig
from core.services.registry import ToolRegistry
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.agent_definition import AgentConfig
    from core.models import ResearchContext


logger = get_logger(__name__)


class ToolRegistryMixin:
    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__name__ not in ("BaseTool", "MCPBaseTool"):
            ToolRegistry.register(cls, name=cls.tool_name)


class BaseTool(BaseModel, ToolRegistryMixin):

    tool_name: ClassVar[str] = None
    description: ClassVar[str] = None

    async def __call__(self, context: ResearchContext, config: AgentConfig, **kwargs) -> str:
        raise NotImplementedError("Execute method must be implemented by subclass")

    def __init_subclass__(cls, **kwargs) -> None:
        cls.tool_name = cls.tool_name or cls.__name__.lower()
        cls.description = cls.description or cls.__doc__ or ""
        super().__init_subclass__(**kwargs)
