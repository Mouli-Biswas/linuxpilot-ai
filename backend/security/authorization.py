"""
authorization.py
----------------
Centralized, Action-Bound Authorization Engine for LinuxPilot AI.

Replaces generic boolean confirmation flags with cryptographically secure,
action-bound, single-use, time-limited authorization tickets.

Security Invariants:
1. Preview vs Approval: Preview creation records proposed operation in PENDING state.
   Explicit user approval action is required to transition to APPROVED.
   Execution requires an APPROVED operation and atomically consumes it (CONSUMED).
2. Action Binding: An authorization ticket is strictly bound to an exact action
   (e.g., 'service.restart') and target resource (e.g., 'service:nginx').
3. Parameter Binding: Any modification to command arguments or parameters
   invalidates the authorization.
4. Postcondition Verification: Tickets record expected state outcome and verify it.
5. Expiry & Replay Prevention: Single-use, short configurable TTL (default 120s),
   atomic state transitions.
6. Immutability: Defensive copying protects all records against caller mutation.
"""

from __future__ import annotations

import copy
import logging
import secrets
import threading
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.database.db import log_authorization_audit
from backend.utils.config import settings

logger = logging.getLogger("linuxpilot.security.authorization")


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class OperationAuthorization(BaseModel):
    operation_id: str
    action: str
    target_resource: str
    parameters: dict[str, Any]
    expected_postconditions: dict[str, Any]
    action_summary: str
    created_at: datetime
    expires_at: datetime
    status: AuthorizationStatus = AuthorizationStatus.PENDING
    approved_at: Optional[datetime] = None
    consumed_at: Optional[datetime] = None


class AuthorizationPreview(BaseModel):
    operation_id: str
    action: str
    target_resource: str
    parameters: dict[str, Any]
    expected_postconditions: dict[str, Any]
    action_summary: str
    status: str
    expires_at: str
    ttl_seconds: int


class AuthorizationDecision(BaseModel):
    is_authorized: bool
    reason: str
    authorization: Optional[OperationAuthorization] = None


def canonicalize_value(val: Any) -> Any:
    """
    Recursively canonicalizes parameters and postconditions for consistent comparison.
    - Strips whitespace from strings.
    - Recursively sorts dictionary keys.
    - Recursively canonicalizes lists/tuples.
    - Preserves explicit None values (distinguishing None from omitted keys).
    """
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        return {
            str(k).strip(): canonicalize_value(v)
            for k, v in sorted(val.items(), key=lambda item: str(item[0]))
        }
    if isinstance(val, (list, tuple)):
        return [canonicalize_value(item) for item in val]
    return val


def structures_match(bound: Any, requested: Any) -> bool:
    """
    Compares two structures after recursive canonicalization.
    Explicitly distinguishes missing fields from explicit None.
    """
    return canonicalize_value(bound) == canonicalize_value(requested)


class AuthorizationManager:
    """
    In-memory thread-safe authorization store and verification engine.
    Ensures that every state-changing operation in LinuxPilot AI is explicitly
    authorized by a valid, approved, unconsumed, action-bound ticket.
    """

    def __init__(self, default_ttl_seconds: int = 120) -> None:
        self._default_ttl_seconds = default_ttl_seconds
        self._authorizations: dict[str, OperationAuthorization] = {}
        self._lock = threading.Lock()

    def create_authorization(
        self,
        action: str,
        target_resource: str,
        parameters: dict[str, Any],
        expected_postconditions: Optional[dict[str, Any]] = None,
        action_summary: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> OperationAuthorization:
        """
        Creates and stores a cryptographically secure authorization ticket in PENDING state.
        Defensively copies all caller dictionaries to guarantee immutability.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl)
        operation_id = f"op_auth_{secrets.token_urlsafe(24)}"

        summary = action_summary or f"Authorize '{action}' on resource '{target_resource}'"

        auth = OperationAuthorization(
            operation_id=operation_id,
            action=action.strip(),
            target_resource=target_resource.strip(),
            parameters=copy.deepcopy(parameters),
            expected_postconditions=copy.deepcopy(expected_postconditions or {}),
            action_summary=summary,
            created_at=now,
            expires_at=expires_at,
            status=AuthorizationStatus.PENDING,
        )

        with self._lock:
            self._authorizations[operation_id] = copy.deepcopy(auth)

        # Audit write outside memory lock
        log_authorization_audit(operation_id, action, target_resource, "PREVIEW_CREATED", summary)
        logger.info(
            "Created PENDING authorization ticket %s for action=%s target=%s (expires in %ds)",
            operation_id,
            action,
            target_resource,
            ttl,
        )
        return copy.deepcopy(auth)

    def get_authorization(self, operation_id: str) -> Optional[OperationAuthorization]:
        with self._lock:
            auth = self._authorizations.get(operation_id)
            return copy.deepcopy(auth) if auth else None

    def approve_authorization(
        self,
        operation_id: Optional[str],
        action: Optional[str] = None,
        target_resource: Optional[str] = None,
        parameters: Optional[dict[str, Any]] = None,
        expected_postconditions: Optional[dict[str, Any]] = None,
    ) -> AuthorizationDecision:
        """
        Explicitly transitions a PENDING authorization ticket to APPROVED.
        Verifies exact action, canonical target, parameters, and postconditions if provided.
        """
        if not operation_id:
            reason = "Missing required operation_id for approval."
            log_authorization_audit("none", action or "unknown", target_resource or "unknown", "APPROVAL_REJECTED", reason)
            return AuthorizationDecision(is_authorized=False, reason=reason)

        now = datetime.now(timezone.utc)
        audit_event = None

        with self._lock:
            auth = self._authorizations.get(operation_id)
            if auth is None:
                reason = f"Invalid or unknown authorization ticket '{operation_id}'."
                audit_event = (operation_id, action or "unknown", target_resource or "unknown", "APPROVAL_REJECTED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason)
            elif auth.status == AuthorizationStatus.CONSUMED:
                reason = "Cannot approve: ticket has already been consumed."
                audit_event = (operation_id, auth.action, auth.target_resource, "REPLAY_PREVENTED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.status == AuthorizationStatus.EXPIRED or now > auth.expires_at:
                auth.status = AuthorizationStatus.EXPIRED
                reason = f"Cannot approve: authorization ticket '{operation_id}' has expired."
                audit_event = (operation_id, auth.action, auth.target_resource, "EXPIRED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.status == AuthorizationStatus.REVOKED:
                reason = f"Cannot approve: authorization ticket '{operation_id}' was revoked."
                audit_event = (operation_id, auth.action, auth.target_resource, "REVOKED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif action and auth.action != action.strip():
                reason = f"Approval action mismatch: ticket is for '{auth.action}', requested '{action}'."
                audit_event = (operation_id, action, auth.target_resource, "ACTION_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif target_resource and auth.target_resource != target_resource.strip():
                reason = f"Approval target mismatch: ticket is for '{auth.target_resource}', requested '{target_resource}'."
                audit_event = (operation_id, auth.action, target_resource, "TARGET_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif parameters is not None and not structures_match(auth.parameters, parameters):
                reason = "Approval parameter mismatch: supplied parameters do not match pending preview."
                audit_event = (operation_id, auth.action, auth.target_resource, "PARAMETER_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif (
                expected_postconditions is not None
                and not structures_match(auth.expected_postconditions, expected_postconditions)
            ):
                reason = "Approval postcondition mismatch: supplied postconditions do not match pending preview."
                audit_event = (operation_id, auth.action, auth.target_resource, "POSTCONDITION_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            else:
                # Transition PENDING -> APPROVED
                auth.status = AuthorizationStatus.APPROVED
                auth.approved_at = now
                snapshot = copy.deepcopy(auth)
                reason = "Authorization ticket successfully approved."
                audit_event = (operation_id, auth.action, auth.target_resource, "APPROVAL_GRANTED", reason)
                decision = AuthorizationDecision(is_authorized=True, reason=reason, authorization=snapshot)

        if audit_event:
            log_authorization_audit(*audit_event)

        return decision

    def revoke_authorization(self, operation_id: str, reason: str = "Revoked by user") -> AuthorizationDecision:
        """
        Revokes a pending or approved ticket, preventing its execution.
        """
        with self._lock:
            auth = self._authorizations.get(operation_id)
            if not auth:
                return AuthorizationDecision(is_authorized=False, reason=f"Ticket '{operation_id}' not found.")
            auth.status = AuthorizationStatus.REVOKED
            snapshot = copy.deepcopy(auth)

        log_authorization_audit(operation_id, snapshot.action, snapshot.target_resource, "REVOKED", reason)
        return AuthorizationDecision(is_authorized=True, reason=reason, authorization=snapshot)

    def check_authorization(
        self,
        operation_id: Optional[str],
        action: str,
        target_resource: str,
        parameters: dict[str, Any],
        expected_postconditions: Optional[dict[str, Any]] = None,
    ) -> AuthorizationDecision:
        """
        Non-destructive check that validates whether an operation is APPROVED and matches
        the bound action, target, parameters, and postconditions.
        Does NOT consume the ticket.
        """
        if not operation_id:
            return AuthorizationDecision(
                is_authorized=False,
                reason="Missing required authorization ticket (operation_id). Client-provided flags alone cannot authorize mutations.",
            )

        now = datetime.now(timezone.utc)
        with self._lock:
            auth = self._authorizations.get(operation_id)
            if auth is None:
                return AuthorizationDecision(
                    is_authorized=False,
                    reason=f"Invalid or unknown authorization ticket '{operation_id}'.",
                )

            if auth.status == AuthorizationStatus.CONSUMED:
                return AuthorizationDecision(
                    is_authorized=False,
                    reason="Authorization ticket has already been used (replay prevented).",
                    authorization=copy.deepcopy(auth),
                )

            if auth.status == AuthorizationStatus.EXPIRED or now > auth.expires_at:
                auth.status = AuthorizationStatus.EXPIRED
                return AuthorizationDecision(
                    is_authorized=False,
                    reason=f"Authorization ticket '{operation_id}' has expired.",
                    authorization=copy.deepcopy(auth),
                )

            if auth.status == AuthorizationStatus.REVOKED:
                return AuthorizationDecision(
                    is_authorized=False,
                    reason=f"Authorization ticket '{operation_id}' has been revoked.",
                    authorization=copy.deepcopy(auth),
                )

            if auth.status == AuthorizationStatus.PENDING:
                return AuthorizationDecision(
                    is_authorized=False,
                    reason="Operation has not been approved. Explicit user approval is required before execution.",
                    authorization=copy.deepcopy(auth),
                )

            if auth.status != AuthorizationStatus.APPROVED:
                return AuthorizationDecision(
                    is_authorized=False,
                    reason=f"Authorization ticket has invalid status: {auth.status}.",
                    authorization=copy.deepcopy(auth),
                )

            if auth.action != action.strip():
                return AuthorizationDecision(
                    is_authorized=False,
                    reason=f"Authorization action mismatch: ticket authorized '{auth.action}', but attempted '{action}'.",
                    authorization=copy.deepcopy(auth),
                )

            if auth.target_resource != target_resource.strip():
                return AuthorizationDecision(
                    is_authorized=False,
                    reason=f"Authorization target mismatch: ticket authorized '{auth.target_resource}', but requested '{target_resource}'.",
                    authorization=copy.deepcopy(auth),
                )

            if not structures_match(auth.parameters, parameters):
                return AuthorizationDecision(
                    is_authorized=False,
                    reason="Authorization parameter mismatch: supplied parameters do not match validated ticket.",
                    authorization=copy.deepcopy(auth),
                )

            if expected_postconditions is not None and not structures_match(
                auth.expected_postconditions, expected_postconditions
            ):
                return AuthorizationDecision(
                    is_authorized=False,
                    reason="Authorization postcondition mismatch: supplied postconditions do not match validated ticket.",
                    authorization=copy.deepcopy(auth),
                )

            return AuthorizationDecision(
                is_authorized=True,
                reason="Authorization verified and ready for execution.",
                authorization=copy.deepcopy(auth),
            )

    def validate_and_consume(
        self,
        operation_id: Optional[str],
        action: str,
        target_resource: str,
        parameters: dict[str, Any],
        expected_postconditions: Optional[dict[str, Any]] = None,
    ) -> AuthorizationDecision:
        """
        Validates the authorization ticket against APPROVED status, action, target,
        parameters, expected postconditions, expiry, and replay status.
        If valid, atomically marks it as CONSUMED.
        """
        if not operation_id:
            reason = "Missing required authorization ticket (operation_id). Client-provided flags alone cannot authorize mutations."
            log_authorization_audit("none", action, target_resource, "EXECUTION_BLOCKED", reason)
            return AuthorizationDecision(is_authorized=False, reason=reason)

        now = datetime.now(timezone.utc)
        audit_event = None

        with self._lock:
            auth = self._authorizations.get(operation_id)
            if auth is None:
                logger.warning("Authorization rejected: ticket %s not found", operation_id)
                reason = f"Invalid or unknown authorization ticket '{operation_id}'."
                audit_event = (operation_id, action, target_resource, "EXECUTION_BLOCKED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason)
            elif auth.status == AuthorizationStatus.CONSUMED:
                logger.warning("Replay attack prevented: ticket %s was already consumed", operation_id)
                reason = "Authorization ticket has already been used (replay prevented)."
                audit_event = (operation_id, action, target_resource, "REPLAY_PREVENTED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.status == AuthorizationStatus.EXPIRED or now > auth.expires_at:
                auth.status = AuthorizationStatus.EXPIRED
                logger.warning("Authorization rejected: ticket %s has expired", operation_id)
                reason = f"Authorization ticket '{operation_id}' has expired."
                audit_event = (operation_id, action, target_resource, "EXPIRED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.status == AuthorizationStatus.REVOKED:
                reason = f"Authorization ticket '{operation_id}' has been revoked."
                audit_event = (operation_id, action, target_resource, "REVOKED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.status == AuthorizationStatus.PENDING:
                logger.warning("Execution blocked: ticket %s is still PENDING (not approved)", operation_id)
                reason = "Operation has not been approved. Explicit user approval is required before execution."
                audit_event = (operation_id, action, target_resource, "EXECUTION_BLOCKED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.status != AuthorizationStatus.APPROVED:
                reason = f"Authorization ticket has invalid status: {auth.status}."
                audit_event = (operation_id, action, target_resource, "EXECUTION_BLOCKED", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.action != action.strip():
                logger.warning("Authorization rejected: action mismatch for %s", operation_id)
                reason = f"Authorization action mismatch: ticket authorized '{auth.action}', but attempted '{action}'."
                audit_event = (operation_id, action, target_resource, "ACTION_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif auth.target_resource != target_resource.strip():
                logger.warning("Authorization rejected: target mismatch for %s", operation_id)
                reason = f"Authorization target mismatch: ticket authorized '{auth.target_resource}', but requested '{target_resource}'."
                audit_event = (operation_id, action, target_resource, "TARGET_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif not structures_match(auth.parameters, parameters):
                logger.warning("Authorization rejected: parameters mismatch for %s", operation_id)
                reason = "Authorization parameter mismatch: supplied parameters do not match validated ticket."
                audit_event = (operation_id, action, target_resource, "PARAMETER_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            elif (
                expected_postconditions is not None
                and not structures_match(auth.expected_postconditions, expected_postconditions)
            ):
                logger.warning("Authorization rejected: postcondition mismatch for %s", operation_id)
                reason = "Authorization postcondition mismatch: supplied postconditions do not match validated ticket."
                audit_event = (operation_id, action, target_resource, "POSTCONDITION_MISMATCH", reason)
                decision = AuthorizationDecision(is_authorized=False, reason=reason, authorization=copy.deepcopy(auth))
            else:
                # Atomically transition APPROVED -> CONSUMED
                auth.status = AuthorizationStatus.CONSUMED
                auth.consumed_at = now
                snapshot = copy.deepcopy(auth)
                reason = "Authorization validated and consumed successfully."
                audit_event = (operation_id, action, target_resource, "CONSUMED", reason)
                decision = AuthorizationDecision(is_authorized=True, reason=reason, authorization=snapshot)
                logger.info("Successfully validated and consumed authorization ticket %s", operation_id)

        if audit_event:
            log_authorization_audit(*audit_event)

        return decision

    def to_preview(self, auth: OperationAuthorization) -> AuthorizationPreview:
        now = datetime.now(timezone.utc)
        ttl_remaining = max(0, int((auth.expires_at - now).total_seconds()))
        return AuthorizationPreview(
            operation_id=auth.operation_id,
            action=auth.action,
            target_resource=auth.target_resource,
            parameters=copy.deepcopy(auth.parameters),
            expected_postconditions=copy.deepcopy(auth.expected_postconditions),
            action_summary=auth.action_summary,
            status=auth.status.value,
            expires_at=auth.expires_at.isoformat(),
            ttl_seconds=ttl_remaining,
        )

    def clear(self) -> None:
        """Testing utility to reset authorizations."""
        with self._lock:
            self._authorizations.clear()


auth_manager = AuthorizationManager()

