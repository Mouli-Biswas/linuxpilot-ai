"""
tool_registry.py
-----------------
Maps the tool names used in a Plan (see agent/planner.py) to the actual
backend callables. This is the single seam between "the LLM decided to
call diagnostics.cpu" and "we actually import and run get_cpu_metrics()".
Centralizing it here means adding a new tool is a one-line registration,
not a change scattered across the orchestrator.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from backend.commands.log_analysis import DmesgQuery, JournalctlQuery, query_dmesg, query_journalctl
from backend.diagnostics.diagnostics import (
    get_cpu_metrics,
    get_disk_metrics,
    get_memory_metrics,
    get_network_metrics,
)
from backend.search.file_search import FileSearchQuery, search_files
from backend.services.service_manager import check_status, restart_service, start_service, stop_service
from backend.validator.command_validator import execute_validated_command

logger = logging.getLogger("linuxpilot.agent.tools")

ToolFn = Callable[..., Any]


def _diagnostics_cpu(args: dict[str, Any]) -> dict:
    return get_cpu_metrics(sample_seconds=args.get("sample_seconds", 0.5)).model_dump()


def _diagnostics_memory(_args: dict[str, Any]) -> dict:
    return get_memory_metrics().model_dump()


def _diagnostics_disk(args: dict[str, Any]) -> dict:
    return get_disk_metrics(
        mount_point=args.get("mount_point", "/"),
        scan_path=args.get("scan_path"),
        top_n=args.get("top_n", 5),
        min_size_mb=args.get("min_size_mb", 0.0),
        name_filter=args.get("name_filter"),
    ).model_dump()


def _diagnostics_network(_args: dict[str, Any]) -> dict:
    return get_network_metrics().model_dump()


def _file_search(args: dict[str, Any]) -> dict:
    query = FileSearchQuery(**args)
    return search_files(query).model_dump()


def _service_status(args: dict[str, Any]) -> dict:
    return check_status(args.get("service_name", "")).model_dump()


def _service_restart(args: dict[str, Any]) -> dict:
    return restart_service(args.get("service_name", "")).model_dump()


def _service_start(args: dict[str, Any]) -> dict:
    return start_service(args.get("service_name", "")).model_dump()


def _service_stop(args: dict[str, Any]) -> dict:
    return stop_service(args.get("service_name", "")).model_dump()


def _logs_journalctl(args: dict[str, Any]) -> dict:
    query = JournalctlQuery(**args)
    return query_journalctl(query).model_dump()


def _logs_dmesg(args: dict[str, Any]) -> dict:
    query = DmesgQuery(**args)
    return query_dmesg(query).model_dump()


def _command_execute(args: dict[str, Any]) -> dict:
    cmd = args.get("command", "")
    confirmed = args.get("confirmed", False)
    result = execute_validated_command(cmd, confirmed=confirmed)
    # Serialize ExecutionResult dataclass cleanly
    val_dict = {
        "verdict": result.validation.verdict.value,
        "category": result.validation.category.value,
        "command": result.validation.command,
        "reason": result.validation.reason,
        "requires_confirmation": result.validation.requires_confirmation,
        "matched_rule": result.validation.matched_rule,
    }
    return {
        "command": result.command,
        "validation": val_dict,
        "executed": result.executed,
        "requires_confirmation": result.requires_confirmation,
        "return_code": result.return_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": result.error,
    }


# Tool name (as emitted by the planner LLM / fallback plans) -> handler.
TOOL_REGISTRY: dict[str, ToolFn] = {
    "diagnostics.cpu": _diagnostics_cpu,
    "diagnostics.memory": _diagnostics_memory,
    "diagnostics.disk": _diagnostics_disk,
    "diagnostics.network": _diagnostics_network,
    "file_search.search": _file_search,
    "service.status": _service_status,
    "service.restart": _service_restart,
    "service.start": _service_start,
    "service.stop": _service_stop,
    "logs.journalctl": _logs_journalctl,
    "logs.dmesg": _logs_dmesg,
    "command.execute": _command_execute,
}



def run_tool(tool_name: str, args: dict[str, Any]) -> dict:
    handler = TOOL_REGISTRY.get(tool_name)
    if handler is None:
        raise KeyError(f"No tool registered for '{tool_name}'")
    try:
        return handler(args)
    except Exception as exc:  # noqa: BLE001 - surface as data, not a crash
        logger.exception("Tool '%s' raised an exception", tool_name)
        return {"error": f"{tool_name} failed: {exc}"}
