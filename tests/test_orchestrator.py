"""
test_orchestrator.py
--------------------
Tests the full AgentOrchestrator pipeline:
- Classification -> Planning -> Execution -> Fast Synthesis
- Latency and timing breakdowns
- Modifying command safety confirmation
- Dangerous command blocking
- Error resilience
"""

import asyncio
import pytest
from backend.agent.orchestrator import orchestrator


def _run(query: str, confirmed: bool = False):
    return asyncio.run(orchestrator.run(query, confirmed=confirmed))


def test_orchestrator_diagnostics_flow():
    res = _run("Why is my computer running slowly?")
    assert res.intent == "DIAGNOSTICS"
    assert res.confidence >= 0.90
    assert len(res.plan) > 0
    assert len(res.step_results) >= 3
    assert "System Diagnostics Report" in res.final_answer
    assert res.total_duration_ms < 5000
    assert res.timings is not None
    assert res.timings.classification_ms >= 0


def test_orchestrator_file_search_flow():
    res = _run("Find Python files larger than 50 MB in my home directory")
    assert res.intent == "FILE_SEARCH"
    assert len(res.plan) == 2
    assert "File Search Results" in res.final_answer
    assert res.total_duration_ms < 6000


def test_orchestrator_service_status_flow():
    res = _run("Show me the status of nginx")
    assert res.intent == "SERVICE_MANAGEMENT"
    assert "Service Status: `nginx`" in res.final_answer


def test_orchestrator_log_analysis_flow():
    res = _run("Show recent system errors")
    assert res.intent == "LOG_ANALYSIS"
    assert "Log Analysis" in res.final_answer


def test_orchestrator_learning_mode_flow():
    res = _run("Explain what chmod 755 means")
    assert res.intent == "LEARNING_MODE"
    assert "chmod 755" in res.final_answer
    assert "rwxr-xr-x" in res.final_answer
    assert res.total_duration_ms < 500


def test_orchestrator_modifying_command_requires_confirmation():
    # Without confirmation
    res = _run("apt install nginx", confirmed=False)
    assert res.intent == "COMMAND_EXECUTION"
    assert "User Confirmation Required" in res.final_answer

    # With confirmation
    res_confirmed = _run("apt install nginx", confirmed=True)
    assert res_confirmed.intent == "COMMAND_EXECUTION"
    assert "Command" in res_confirmed.final_answer


def test_orchestrator_dangerous_command_blocked():
    res = _run("rm -rf /")
    assert res.intent == "COMMAND_EXECUTION"
    assert "Command Blocked by Safety Layer" in res.final_answer
    assert "BLOCKED" in res.final_answer


def test_orchestrator_timings_structure():
    res = _run("df -h")
    assert res.timings is not None
    assert hasattr(res.timings, "classification_ms")
    assert hasattr(res.timings, "planning_ms")
    assert hasattr(res.timings, "tool_execution_ms")
    assert hasattr(res.timings, "summarization_ms")
    assert hasattr(res.timings, "total_ms")
    assert res.total_duration_ms >= 0


def test_orchestrator_empty_search_graceful():
    res = _run("Find nonexistent_xyz_files_123.abc in ~")
    assert res.intent == "FILE_SEARCH"
    assert "File Search Results" in res.final_answer
    assert "No matching files were found" in res.final_answer
