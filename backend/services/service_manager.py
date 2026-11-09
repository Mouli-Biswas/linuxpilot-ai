"""
service_manager.py
-------------------
Safely checks, restarts, starts, and stops a fixed allow-list of system services
via systemctl with centralized action-bound authorization and strict postcondition
verification.

Safety & Security Invariants:
1. Lookup table resolution: Service names are strictly resolved through a fixed map.
2. Allowlist enforcement: Units must be present in settings.ALLOWED_SERVICES.
3. Centralized authorization: All mutating actions (restart, start, stop) require a valid,
   unconsumed, action-bound authorization ticket (operation_id).
4. No direct execution bypass: Direct API calls, internal tools, and fallback planner paths
   cannot bypass authorization or ALLOW_COMMAND_EXECUTION.
5. Strict postcondition verification: Success is reported ONLY when the expected service state
   is verified after execution.
6. Safe argument list: No user-supplied string is ever passed to a shell (shell=False).
"""

from __future__ import annotations

import logging
import subprocess
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from backend.database.db import log_authorization_audit
from backend.security.authorization import (
    AuthorizationPreview,
    auth_manager,
)
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
    output: str = ""
    error: Optional[str] = None
    requires_confirmation: bool = False
    authorization: Optional[AuthorizationPreview] = None
    authorization_status: Optional[str] = None
    precondition_met: Optional[bool] = None
    postcondition_verified: Optional[bool] = None


class ServiceManagerError(RuntimeError):
    pass


def _resolve_unit(service_name: str) -> str:
    cleaned = service_name.strip().lower()
    unit = _SERVICE_UNIT_MAP.get(cleaned)
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
    """
    Read-only inspection of service state. Requires no authorization prompts.
    """
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
            postcondition_verified=True,
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


def restart_service(service_name: str, operation_id: Optional[str] = None) -> ServiceResult:
    """
    Restarts a system service with action-bound authorization and verified postcondition.
    """
    return _execute_service_mutation(
        service_name=service_name,
        action=ServiceAction.RESTART,
        expected_active=True,
        operation_id=operation_id,
    )


def start_service(service_name: str, operation_id: Optional[str] = None) -> ServiceResult:
    """
    Starts a system service with action-bound authorization and verified postcondition.
    """
    return _execute_service_mutation(
        service_name=service_name,
        action=ServiceAction.START,
        expected_active=True,
        operation_id=operation_id,
    )


def stop_service(service_name: str, operation_id: Optional[str] = None) -> ServiceResult:
    """
    Stops a system service with action-bound authorization and verified postcondition.
    """
    return _execute_service_mutation(
        service_name=service_name,
        action=ServiceAction.STOP,
        expected_active=False,
        operation_id=operation_id,
    )


def _execute_service_mutation(
    service_name: str,
    action: ServiceAction,
    expected_active: bool,
    operation_id: Optional[str] = None,
) -> ServiceResult:
    unit = _resolve_unit(service_name)
    canonical_action = f"service.{action.value}"
    target_resource = f"service:{unit}"
    parameters = {"service_name": service_name, "unit": unit}
    expected_postconditions = {"active": expected_active}

    # 1. Preview / Authorization Check
    if not operation_id:
        auth = auth_manager.create_authorization(
            action=canonical_action,
            target_resource=target_resource,
            parameters=parameters,
            expected_postconditions=expected_postconditions,
            action_summary=f"Execute {action.value.upper()} on system service '{service_name}' ({unit})",
        )
        preview = auth_manager.to_preview(auth)
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            requires_confirmation=True,
            error=f"Service {action.value} requires explicit action-bound user approval before execution.",
            authorization=preview,
            authorization_status="PENDING",
        )

    # 2. Non-destructively check authorization status (must be APPROVED)
    decision = auth_manager.check_authorization(
        operation_id=operation_id,
        action=canonical_action,
        target_resource=target_resource,
        parameters=parameters,
        expected_postconditions=expected_postconditions,
    )

    if not decision.is_authorized:
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            requires_confirmation=False,
            error=f"Authorization rejected: {decision.reason}",
            authorization_status="REJECTED",
        )

    # 3. Master Execution Switch Check BEFORE consuming ticket
    if not settings.ALLOW_COMMAND_EXECUTION:
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            requires_confirmation=False,
            output="",
            error="Execution disabled: ALLOW_COMMAND_EXECUTION=false in environment configuration (dry-run mode).",
            authorization_status="AUTHORIZED_BUT_DISABLED",
        )

    # 4. Atomically consume the authorization ticket
    consume_decision = auth_manager.validate_and_consume(
        operation_id=operation_id,
        action=canonical_action,
        target_resource=target_resource,
        parameters=parameters,
        expected_postconditions=expected_postconditions,
    )

    if not consume_decision.is_authorized:
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            requires_confirmation=False,
            error=f"Authorization consumption failed: {consume_decision.reason}",
            authorization_status="REJECTED",
        )

    # 5. Precondition check & idempotency detection
    pre_status = check_status(service_name)
    precondition_met = True
    if action == ServiceAction.START and pre_status.active is True:
        logger.info("Service %s is already active before start (idempotent)", unit)
    elif action == ServiceAction.STOP and pre_status.active is False:
        logger.info("Service %s is already stopped before stop (idempotent)", unit)

    # 6. Execute Mutation via systemctl argument list (shell=False)
    log_authorization_audit(
        operation_id,
        canonical_action,
        target_resource,
        "EXECUTION_ATTEMPTED",
        f"Executing systemctl {action.value} {unit}",
    )

    try:
        result = _run_systemctl([action.value, unit])
        command_success = (result.returncode == 0)
    except subprocess.TimeoutExpired:
        log_authorization_audit(
            operation_id,
            canonical_action,
            target_resource,
            "EXECUTION_FAILED",
            f"Timed out after {settings.COMMAND_TIMEOUT_SECONDS}s",
        )
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            output="",
            error=f"systemctl {action.value} timed out after {settings.COMMAND_TIMEOUT_SECONDS}s.",
            authorization_status="FAILED",
            precondition_met=precondition_met,
            postcondition_verified=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("%s failed for %s: %s", action.value, unit, exc)
        log_authorization_audit(
            operation_id,
            canonical_action,
            target_resource,
            "EXECUTION_FAILED",
            str(exc),
        )
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            output="",
            error=str(exc),
            authorization_status="FAILED",
            precondition_met=precondition_met,
            postcondition_verified=False,
        )

    # 7. Strict Postcondition Verification
    post_status = check_status(service_name)
    if not post_status.success:
        log_authorization_audit(
            operation_id,
            canonical_action,
            target_resource,
            "VERIFICATION_FAILED",
            "Post-status check failed to determine service state",
        )
        return ServiceResult(
            service=service_name,
            unit=unit,
            action=action.value,
            success=False,
            output=result.stdout.strip() or f"{action.value} command executed.",
            error=f"Post-execution verification could not determine service state: {post_status.error}",
            authorization_status="CONSUMED",
            precondition_met=precondition_met,
            postcondition_verified=False,
        )

    postcondition_verified = (post_status.active == expected_active)
    final_success = command_success and postcondition_verified

    if final_success:
        log_authorization_audit(
            operation_id,
            canonical_action,
            target_resource,
            "POSTCONDITION_VERIFIED",
            f"active={post_status.active}",
        )
    else:
        log_authorization_audit(
            operation_id,
            canonical_action,
            target_resource,
            "VERIFICATION_FAILED",
            f"expected active={expected_active}, actual active={post_status.active}",
        )

    error_msg = None
    if not command_success:
        error_msg = result.stderr.strip() or f"systemctl {action.value} failed with return code {result.returncode}."
    elif not postcondition_verified:
        error_msg = (
            f"Postcondition verification failed: service '{service_name}' ({unit}) was expected to have "
            f"active={expected_active} after {action.value}, but actual state is active={post_status.active}."
        )

    return ServiceResult(
        service=service_name,
        unit=unit,
        action=action.value,
        success=final_success,
        active=post_status.active,
        output=result.stdout.strip() or f"{action.value} command executed.",
        error=error_msg,
        authorization_status="CONSUMED",
        precondition_met=precondition_met,
        postcondition_verified=postcondition_verified,
    )
