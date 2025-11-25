#!/usr/bin/env python3
"""Simple test script for SGR Agent."""

import asyncio
import sys

# Add src to path
sys.path.insert(0, "src")

from core.agent_config import GlobalConfig
from core.agent_factory import AgentFactory
from core.agents.sgr_agent import SGRAgent
from core.tools import ClarificationTool, FinalAnswerTool, ReasoningTool, WebSearchTool
from utils.config import CONFIG


async def test_agent():
    """Test agent with a simple question."""

    print("=" * 60)
    print("SGR Agent Test")
    print("=" * 60)

    # Check OpenAI API key
    if not CONFIG.openai.api_key:
        print("\n❌ ОШИБКА: OpenAI API key не настроен!")
        print("Обновите src/config-local.yml:")
        print("  openai:")
        print("    api_key: 'ваш-ключ-здесь'")
        return

    print(f"\n✓ OpenAI API key: {CONFIG.openai.api_key[:10]}...")
    print(f"✓ Model: {CONFIG.openai.model}")
    print(f"✓ Base URL: {CONFIG.openai.base_url}")

    # Initialize OpenAI client
    # Initialize GlobalConfig
    config = GlobalConfig()
    print("✓ GlobalConfig initialized")
    print("✓ OpenAI client will be created by AgentFactory")

    # Test question
    question = "Что такое Python и для чего он используется?"
    print(f"\n📝 Вопрос: {question}")
    print("\n" + "=" * 60)
    print("Запуск агента...")
    print("=" * 60 + "\n")

    try:
        from core.agent_definition import AgentDefinition

        # Create agent definition
        agent_def = AgentDefinition(
            name="test_agent",
            base_class=SGRAgent,
            tools=[
                ReasoningTool,
                FinalAnswerTool,
                # WebSearchTool,  # Раскомментируйте если настроен Tavily API key
                # ClarificationTool,
            ],
        )

        print("✓ Agent definition created")

        # Create agent using factory
        agent = await AgentFactory.create(agent_def=agent_def, task=question)

        print("✓ Agent created\n")

        # Run agent
        result = await agent.execute()

        print("\n" + "=" * 60)
        print("Результат:")
        print("=" * 60)
        print(result)

    except Exception as e:
        print(f"\n❌ Ошибка при работе агента: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_agent())
