"""
service_manager.py
-------------------
Safely checks and restarts a fixed allow-list of system services via
systemctl. No user-supplied string is ever concatenated into a shell
command — service names are resolved through a lookup table, and every
subprocess call uses an argument list (never shell=True).
"""

from __future__ import annotations

import logging
import subprocess
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from backend.utils.config import settings

logger = logging.getLogger("linuxpilot.services")

# Canonical service key -> actual systemd unit name. Anything not in this
# map is rejected outright, regardless of what the AI layer extracted.
_SERVICE_UNIT_MAP: dict[str, str] = {
    "docker": "docker",
    "apache": "apache2",
    "apache2": "apache2",
    "nginx": "nginx",
    "ssh": "ssh",
    "sshd": "ssh",
    "mysql": "mysql",
    "postgresql": "postgresql",
    "postgres": "postgresql",
}


class ServiceAction(str, Enum):
    STATUS = "status"
    RESTART = "restart"
    START = "start"
    STOP = "stop"


class ServiceResult(BaseModel):
    service: str
    unit: str
    action: str
    success: bool
    active: Optional[bool] = None
    output: str
    error: Optional[str] = None


class ServiceManagerError(RuntimeError):
    pass


def _resolve_unit(service_name: str) -> str:
    unit = _SERVICE_UNIT_MAP.get(service_name.strip().lower())
    if unit is None:
        raise ServiceManagerError(
            f"'{service_name}' is not a recognized/allowed service. "
            f"Allowed: {sorted(set(_SERVICE_UNIT_MAP.values()))}"
        )
    if unit not in settings.ALLOWED_SERVICES:
        raise ServiceManagerError(f"'{unit}' is not enabled in ALLOWED_SERVICES config.")
    return unit


def _run_systemctl(args: list[str]) -> subprocess.CompletedProcess:
    # args is always a list built from our own code + a validated unit name,
    # never raw user text -> no shell=True, no injection surface.
    return subprocess.run(
        ["systemctl", *args],
        capture_output=True,
        text=True,
        timeout=settings.COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


def check_status(service_name: str) -> ServiceResult:
    unit = _resolve_unit(service_name)
    try:
        result = _run_systemctl(["is-active", unit])
        active = result.stdout.strip() == "active"
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=ServiceAction.STATUS.value,
            success=True,
            active=active,
            output=result.stdout.strip() or result.stderr.strip(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("Status check failed for %s: %s", unit, exc)
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=ServiceAction.STATUS.value,
            success=False,
            output="",
            error=str(exc),
        )


def restart_service(service_name: str) -> ServiceResult:
    unit = _resolve_unit(service_name)
    if not settings.ALLOW_COMMAND_EXECUTION:
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=ServiceAction.RESTART.value,
            success=False,
            output="",
            error="Execution disabled: ALLOW_COMMAND_EXECUTION=false. "
            "This is a dry-run environment; enable execution to actually restart services.",
        )
    try:
        result = _run_systemctl(["restart", unit])
        success = result.returncode == 0
        status_after = check_status(service_name)
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=ServiceAction.RESTART.value,
            success=success,
            active=status_after.active,
            output=result.stdout.strip() or "Restart command completed.",
            error=result.stderr.strip() or None if not success else None,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("Restart failed for %s: %s", unit, exc)
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=ServiceAction.RESTART.value,
            success=False,
            output="",
            error=str(exc),
        )


def start_service(service_name: str) -> ServiceResult:
    return _start_or_stop(service_name, ServiceAction.START)


def stop_service(service_name: str) -> ServiceResult:
    return _start_or_stop(service_name, ServiceAction.STOP)


def _start_or_stop(service_name: str, action: ServiceAction) -> ServiceResult:
    unit = _resolve_unit(service_name)
    if not settings.ALLOW_COMMAND_EXECUTION:
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            output="",
            error="Execution disabled: ALLOW_COMMAND_EXECUTION=false.",
        )
    try:
        result = _run_systemctl([action.value, unit])
        success = result.returncode == 0
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=success,
            output=result.stdout.strip() or f"{action.value} completed.",
            error=result.stderr.strip() or None if not success else None,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ServiceResult(
            service=service_name, unit=unit, action=action.value, success=False, output="", error=str(exc)
        )
