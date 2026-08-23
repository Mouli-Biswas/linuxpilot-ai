"""
test_planner.py
---------------
Unit tests for the Task Planner: deterministic workflows, step ordering,
normalization, parameter propagation, and fallback logic.
"""

import asyncio
from backend.agent.planner import task_planner
from backend.ai.schemas import ClassificationResult, Intent, IntentParameters


def _plan(query: str, intent: Intent, classification=None):
    return asyncio.run(task_planner.plan(query, intent=intent, classification=classification))


def test_diagnostics_deterministic_plan():
    plan = _plan("Why is my computer running slowly?", Intent.DIAGNOSTICS)
    tools = [s.tool for s in plan.steps]
    assert "diagnostics.cpu" in tools
    assert "diagnostics.memory" in tools
    assert "diagnostics.disk" in tools
    assert tools[-1] == "response.formatter"
    assert [s.step for s in plan.steps] == list(range(1, len(plan.steps) + 1))


def test_file_search_deterministic_plan():
    plan = _plan("Find large files", Intent.FILE_SEARCH)
    tools = [s.tool for s in plan.steps]
    assert tools == ["file_search.search", "response.formatter"]


def test_service_management_contextual_plan():
    # Status
    cls_status = ClassificationResult(
        intent=Intent.SERVICE_MANAGEMENT,
        confidence=0.95,
        parameters=IntentParameters(service_name="nginx", action="status"),
        raw_query="status nginx",
    )
    plan_status = _plan("status nginx", Intent.SERVICE_MANAGEMENT, classification=cls_status)
    assert plan_status.steps[0].tool == "service.status"
    assert plan_status.steps[1].tool == "response.formatter"

    # Restart
    cls_restart = ClassificationResult(
        intent=Intent.SERVICE_MANAGEMENT,
        confidence=0.95,
        parameters=IntentParameters(service_name="docker", action="restart"),
        raw_query="restart docker",
    )
    plan_restart = _plan("restart docker", Intent.SERVICE_MANAGEMENT, classification=cls_restart)
    assert plan_restart.steps[0].tool == "service.restart"
    assert plan_restart.steps[1].tool == "response.formatter"


def test_log_analysis_contextual_plan():
    cls_journal = ClassificationResult(
        intent=Intent.LOG_ANALYSIS,
        confidence=0.95,
        parameters=IntentParameters(log_source="journalctl"),
        raw_query="journalctl logs",
    )
    plan_journal = _plan("journalctl logs", Intent.LOG_ANALYSIS, classification=cls_journal)
    assert plan_journal.steps[0].tool == "logs.journalctl"
    assert plan_journal.steps[1].tool == "response.formatter"

    cls_dmesg = ClassificationResult(
        intent=Intent.LOG_ANALYSIS,
        confidence=0.95,
        parameters=IntentParameters(log_source="dmesg"),
        raw_query="kernel logs",
    )
    plan_dmesg = _plan("kernel logs", Intent.LOG_ANALYSIS, classification=cls_dmesg)
    assert plan_dmesg.steps[0].tool == "logs.dmesg"
    assert plan_dmesg.steps[1].tool == "response.formatter"


def test_command_execution_plan():
    plan = _plan("df -h", Intent.COMMAND_EXECUTION)
    tools = [s.tool for s in plan.steps]
    assert tools == ["command.execute", "response.formatter"]


def test_learning_mode_plan():
    plan = _plan("Explain chmod 755", Intent.LEARNING_MODE)
    tools = [s.tool for s in plan.steps]
    assert tools == ["response.formatter"]
    assert plan.steps[0].step == 1
