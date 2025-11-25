import logging
import os
from pathlib import Path
from typing import ClassVar, Self

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.agent_definition import AgentConfig, Definitions
from utils.config import CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

# Default prompt file paths
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
DEFAULT_SYSTEM_PROMPT = os.path.join(PROMPTS_DIR, "system_prompt.txt")
DEFAULT_INITIAL_USER_REQUEST = os.path.join(PROMPTS_DIR, "initial_user_request.txt")
DEFAULT_CLARIFICATION_RESPONSE = os.path.join(PROMPTS_DIR, "clarification_response.txt")


class GlobalConfig(BaseSettings, AgentConfig, Definitions):
    """GlobalConfig adapter that uses CONFIG from utils.config instead of Pydantic Settings."""

    _instance: ClassVar[Self | None] = None
    _initialized: ClassVar[bool] = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, *args, **kwargs):
        if self._initialized:
            return

        # Build kwargs from CONFIG if not provided
        if not kwargs:
            # Only include search if Tavily API key is provided
            search_config = None
            if CONFIG.search.tavily_api_key:
                search_config = {
                    "tavily_api_key": CONFIG.search.tavily_api_key,
                    "tavily_api_base_url": CONFIG.search.tavily_api_base_url,
                    "max_searches": CONFIG.search.max_searches,
                    "max_results": CONFIG.search.max_results,
                    "content_limit": CONFIG.search.content_limit,
                }

            kwargs = {
                "llm": {
                    "api_key": CONFIG.openai.api_key,
                    "base_url": CONFIG.openai.base_url,
                    "model": CONFIG.openai.model,
                    "max_tokens": CONFIG.openai.max_tokens,
                    "temperature": CONFIG.openai.temperature,
                    "proxy": CONFIG.openai.proxy if CONFIG.openai.proxy else None,
                },
                "search": search_config,
                "execution": {
                    "max_clarifications": CONFIG.execution.max_clarifications,
                    "max_iterations": CONFIG.execution.max_iterations,
                    "mcp_context_limit": CONFIG.execution.mcp_context_limit,
                    "logs_dir": CONFIG.execution.logs_dir,
                    "reports_dir": CONFIG.execution.reports_dir,
                },
                "prompts": {
                    "system_prompt_file": DEFAULT_SYSTEM_PROMPT,
                    "initial_user_request_file": DEFAULT_INITIAL_USER_REQUEST,
                    "clarification_response_file": DEFAULT_CLARIFICATION_RESPONSE,
                    "system_prompt_str": None,
                    "initial_user_request_str": None,
                    "clarification_response_str": None,
                },
                "mcp": {
                    "mcpServers": CONFIG.mcp.mcpServers if CONFIG.mcp.mcpServers else {},
                },
                "agents": CONFIG.agents if CONFIG.agents else {},
            }

        super().__init__(**kwargs)
        self.__class__._initialized = True

    model_config = SettingsConfigDict(
        env_prefix="SGR__",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> Self:
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")
        config_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        main_config_agents = config_data.pop("agents", {})
        if cls._instance is None:
            cls._instance = cls(
                **config_data,
            )
        else:
            cls._initialized = False
            cls._instance = cls(**config_data, agents=cls._instance.agents)
        # agents should be initialized last to allow merging
        cls._definitions_from_dict({"agents": main_config_agents})
        return cls._instance

    @classmethod
    def _definitions_from_dict(cls, agents_data: dict) -> Self:
        for agent_name, agent_config in agents_data.get("agents", {}).items():
            agent_config["name"] = agent_name

        custom_agents = Definitions(**agents_data).agents

        # Check for agents that will be overridden
        overridden = set(cls._instance.agents.keys()) & set(custom_agents.keys())
        if overridden:
            logger.warning(f"Loaded agents will override existing agents: " f"{', '.join(sorted(overridden))}")

        cls._instance.agents.update(custom_agents)
        return cls._instance

    @classmethod
    def definitions_from_yaml(cls, agents_yaml_path: str) -> Self:
        """Load agent definitions from YAML file and merge with existing
        agents.

        Args:
            agents_yaml_path: Path to YAML file with agent definitions

        Returns:
            GlobalConfig instance with merged agents

        Raises:
            FileNotFoundError: If YAML file not found
            ValueError: If YAML file doesn't contain 'agents' key
        """
        agents_yaml_path = Path(agents_yaml_path)
        if not agents_yaml_path.exists():
            raise FileNotFoundError(f"Agents definitions file not found: {agents_yaml_path}")

        yaml_data = yaml.safe_load(agents_yaml_path.read_text(encoding="utf-8"))
        if not yaml_data.get("agents"):
            raise ValueError(f"Agents definitions file must contain 'agents' key: {agents_yaml_path}")

        return cls._definitions_from_dict(yaml_data)
