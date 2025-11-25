from core.base_tool import BaseTool
from core.next_step_tool import (
    NextStepToolsBuilder,
    NextStepToolStub,
)
from core.tools.adapt_plan_tool import AdaptPlanTool
from core.tools.clarification_tool import ClarificationTool
from core.tools.create_report_tool import CreateReportTool
from core.tools.extract_page_content_tool import ExtractPageContentTool
from core.tools.final_answer_tool import FinalAnswerTool
from core.tools.generate_plan_tool import GeneratePlanTool
from core.tools.reasoning_tool import ReasoningTool
from core.tools.web_search_tool import WebSearchTool

# Tool lists for backward compatibility
system_agent_tools = [
    ClarificationTool,
    GeneratePlanTool,
    AdaptPlanTool,
    FinalAnswerTool,
    ReasoningTool,
]

research_agent_tools = [
    WebSearchTool,
    ExtractPageContentTool,
    CreateReportTool,
]

__all__ = [
    # Base classes
    "BaseTool",
    "NextStepToolStub",
    "NextStepToolsBuilder",
    # Individual tools
    "ClarificationTool",
    "GeneratePlanTool",
    "WebSearchTool",
    "ExtractPageContentTool",
    "AdaptPlanTool",
    "CreateReportTool",
    "FinalAnswerTool",
    "ReasoningTool",
    # Tool lists
    "NextStepToolStub",
    "NextStepToolsBuilder",
    # Tool Collections
    "system_agent_tools",
    "research_agent_tools",
]
