"""
planner.py
----------
Turns a natural-language query into an ordered list of executable
sub-tasks for LinuxPilot AI.

Performance strategy:
- DIAGNOSTICS, FILE_SEARCH, SERVICE_MANAGEMENT, LOG_ANALYSIS,
  COMMAND_EXECUTION, and LEARNING_MODE have deterministic fast-path plans.
- Predictable workflows NEVER call Ollama for planning.
- Every plan is guaranteed to end with llm.summarize (or a synthesis step).
- If the LLM planner is invoked for genuinely variable workflows and fails,
  a safe fallback plan is returned.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.ai.ollama_client import OllamaError, ollama_client
from backend.ai.prompts import TASK_PLANNER_SYSTEM_PROMPT
from backend.ai.schemas import ClassificationResult, Intent

logger = logging.getLogger("linuxpilot.agent.planner")


# ============================================================================
# PLAN MODELS
# ============================================================================

class PlanStep(BaseModel):
    step: int
    tool: str
    description: str
    args: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    steps: list[PlanStep]


# ============================================================================
# DETERMINISTIC PLAN TEMPLATES
# ============================================================================

_DETERMINISTIC_PLANS: dict[Intent, tuple[dict[str, Any], ...]] = {
    Intent.DIAGNOSTICS: (
        {
            "step": 1,
            "tool": "diagnostics.cpu",
            "description": "Check CPU usage and load average.",
            "args": {},
        },
        {
            "step": 2,
            "tool": "diagnostics.memory",
            "description": "Check memory and swap usage.",
            "args": {},
        },
        {
            "step": 3,
            "tool": "diagnostics.disk",
            "description": "Check disk usage.",
            "args": {},
        },
        {
            "step": 4,
            "tool": "response.formatter",
            "description": "Build deterministic diagnostic response.",
            "args": {},
        },
    ),
    Intent.FILE_SEARCH: (
        {
            "step": 1,
            "tool": "file_search.search",
            "description": "Search for matching files in filesystem.",
            "args": {},
        },
        {
            "step": 2,
            "tool": "response.formatter",
            "description": "Format file search results.",
            "args": {},
        },
    ),
    Intent.SERVICE_MANAGEMENT: (
        {
            "step": 1,
            "tool": "service.status",
            "description": "Check system service status.",
            "args": {},
        },
        {
            "step": 2,
            "tool": "response.formatter",
            "description": "Summarize service state.",
            "args": {},
        },
    ),
    Intent.LOG_ANALYSIS: (
        {
            "step": 1,
            "tool": "logs.journalctl",
            "description": "Retrieve recent system log entries.",
            "args": {},
        },
        {
            "step": 2,
            "tool": "response.formatter",
            "description": "Summarize log findings.",
            "args": {},
        },
    ),
    Intent.COMMAND_EXECUTION: (
        {
            "step": 1,
            "tool": "command.execute",
            "description": "Validate and execute requested command.",
            "args": {},
        },
        {
            "step": 2,
            "tool": "response.formatter",
            "description": "Format command execution result.",
            "args": {},
        },
    ),
    Intent.LEARNING_MODE: (
        {
            "step": 1,
            "tool": "response.formatter",
            "description": "Explain the requested command or Linux concept.",
            "args": {},
        },
    ),
}

_FALLBACK_PLANS = _DETERMINISTIC_PLANS


# ============================================================================
# TASK PLANNER
# ============================================================================

class TaskPlanner:
    def __init__(self, client=ollama_client) -> None:
        self.client = client

    @staticmethod
    def _build_plan(steps: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> Plan:
        return Plan(
            steps=[
                PlanStep(**step_data)
                for step_data in steps
            ]
        )

    def _build_deterministic_plan(
        self,
        intent: Intent,
        classification: Optional[ClassificationResult] = None,
    ) -> Plan:
        """Builds a contextualized deterministic plan without LLM calls."""
        if intent == Intent.SERVICE_MANAGEMENT and classification and classification.parameters.action:
            action = classification.parameters.action.lower()
            if action in {"restart", "start", "stop"}:
                tool_name = f"service.{action}"
                desc = f"Execute service {action}."
            else:
                tool_name = "service.status"
                desc = "Check system service status."
            return self._build_plan([
                {"step": 1, "tool": tool_name, "description": desc, "args": {}},
                {"step": 2, "tool": "response.formatter", "description": "Summarize service state.", "args": {}},
            ])

        if intent == Intent.LOG_ANALYSIS and classification and classification.parameters.log_source:
            source = classification.parameters.log_source.lower()
            tool_name = "logs.dmesg" if "dmesg" in source else "logs.journalctl"
            return self._build_plan([
                {"step": 1, "tool": tool_name, "description": f"Retrieve recent entries from {source}.", "args": {}},
                {"step": 2, "tool": "response.formatter", "description": "Summarize log findings.", "args": {}},
            ])

        template = _DETERMINISTIC_PLANS.get(intent, _DETERMINISTIC_PLANS[Intent.LEARNING_MODE])
        return self._build_plan(template)

    async def plan(
        self,
        query: str,
        intent: Optional[Intent] = None,
        classification: Optional[ClassificationResult] = None,
    ) -> Plan:
        # ====================================================================
        # FAST DETERMINISTIC PATH
        # ====================================================================
        if intent in _DETERMINISTIC_PLANS:
            logger.debug("Using deterministic plan for intent=%s", intent.value)
            return self._build_deterministic_plan(intent, classification)

        # ====================================================================
        # LLM PLANNER PATH (for custom/unknown intents)
        # ====================================================================
        prompt = (
            query
            if intent is None
            else f"Intent: {intent.value}\nQuery: {query}"
        )

        try:
            if self.client is None:
                raise OllamaError("No Ollama client configured for planner.")

            raw = await self.client.generate_json(
                prompt=prompt,
                system=TASK_PLANNER_SYSTEM_PROMPT,
            )

            if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
                raise ValueError("Planner response missing 'steps' list.")

            steps: list[PlanStep] = []
            for step_data in raw["steps"]:
                if not isinstance(step_data, dict):
                    continue
                try:
                    steps.append(PlanStep(**step_data))
                except (TypeError, ValueError) as exc:
                    logger.warning("Ignoring invalid planner step: %s", exc)

            if not steps:
                raise ValueError("Planner returned no valid steps.")

            if steps[-1].tool != "llm.summarize":
                steps.append(
                    PlanStep(
                        step=len(steps) + 1,
                        tool="llm.summarize",
                        description="Summarize findings.",
                        args={},
                    )
                )

            for index, step in enumerate(steps, start=1):
                step.step = index

            return Plan(steps=steps)

        except (OllamaError, KeyError, TypeError, ValueError, Exception) as exc:
            logger.warning(
                "Planner LLM call failed (%s); using fallback plan for intent=%s",
                exc,
                intent,
            )
            fallback = _FALLBACK_PLANS.get(
                intent or Intent.LEARNING_MODE,
                _FALLBACK_PLANS[Intent.LEARNING_MODE],
            )
            return self._build_plan(fallback)


task_planner = TaskPlanner()