#!/usr/bin/env python3
"""Test script for AgentService - iterative debugging."""

import asyncio
import sys

# Add src to path
sys.path.insert(0, "src")


async def test_service():
    """Test AgentService with debugging."""

    print("=" * 70)
    print("AgentService Test - Iterative Debugging")
    print("=" * 70)

    # Step 1: Check config
    print("\n[1/5] Checking configuration...")
    try:
        from utils.config import CONFIG
        print(f"  ✓ Config loaded")
        print(f"  - OpenAI API key: {CONFIG.openai.api_key[:10] if CONFIG.openai.api_key else 'NOT SET'}...")
        print(f"  - OpenAI model: {CONFIG.openai.model}")
        print(f"  - Tavily API key: {CONFIG.search.tavily_api_key[:10] if CONFIG.search.tavily_api_key else 'NOT SET'}")
    except Exception as e:
        print(f"  ✗ Config error: {e}")
        return

    # Step 2: Test GlobalConfig
    print("\n[2/5] Testing GlobalConfig...")
    try:
        from core.agent_config import GlobalConfig
        config = GlobalConfig()
        print(f"  ✓ GlobalConfig initialized")
        print(f"  - LLM API key: {config.llm.api_key[:10] if config.llm.api_key else 'NOT SET'}...")
        print(f"  - Search config: {config.search is not None}")
        if config.search:
            print(f"  - Tavily API key: {config.search.tavily_api_key[:10] if config.search.tavily_api_key else 'NOT SET'}")
    except Exception as e:
        print(f"  ✗ GlobalConfig error: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 3: Test AgentDefinition creation
    print("\n[3/5] Testing AgentDefinition creation...")
    try:
        from core.agent_definition import AgentDefinition
        from core.agents.sgr_agent import SGRAgent
        from core.tools import ReasoningTool, FinalAnswerTool

        # Try without search (should work)
        agent_def = AgentDefinition(
            name="test_agent",
            base_class=SGRAgent,
            tools=[
                ReasoningTool,
                FinalAnswerTool,
            ],
            search=None,  # Explicitly disable search
        )
        print(f"  ✓ AgentDefinition created successfully")
        print(f"  - Name: {agent_def.name}")
        print(f"  - Tools: {len(agent_def.tools)}")
        print(f"  - Search enabled: {agent_def.search is not None}")
    except Exception as e:
        print(f"  ✗ AgentDefinition error: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 4: Test AgentFactory
    print("\n[4/5] Testing AgentFactory...")
    try:
        from core.agent_factory import AgentFactory

        agent = await AgentFactory.create(
            agent_def=agent_def,
            task="Привет! Кто ты?"
        )
        print(f"  ✓ Agent created successfully")
        print(f"  - Agent ID: {agent.id}")
        print(f"  - Toolkit size: {len(agent.toolkit)}")
    except Exception as e:
        print(f"  ✗ AgentFactory error: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 5: Test agent run
    print("\n[5/5] Testing agent execution...")
    try:
        question = "Что такое Python?"
        print(f"  Question: {question}")
        print(f"  Running agent...\n")

        await agent.execute()

        print(f"\n  ✓ Agent completed successfully!")
        print("\n" + "=" * 70)
        print("RESULT:")
        print("=" * 70)

        # Get result from agent context
        result = agent._context.execution_result
        if result:
            if hasattr(result, "final_answer"):
                print(result.final_answer)
            else:
                print(result)
        else:
            print("No result returned by agent")

        print("=" * 70)

    except Exception as e:
        print(f"  ✗ Agent execution error: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n✓ All tests passed!")


if __name__ == "__main__":
    try:
        asyncio.run(test_service())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
