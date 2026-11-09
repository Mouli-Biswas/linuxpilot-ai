"""
routes_auth.py
--------------
Dedicated FastAPI endpoints for explicit authorization lifecycle management:
- POST /api/auth/approve: Explicit user approval transition (PENDING -> APPROVED).
- POST /api/auth/revoke: Revoke an authorization ticket.
- GET  /api/auth/{operation_id}: Inspect ticket status and details.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.security.authorization import (
    AuthorizationPreview,
    auth_manager,
)

logger = logging.getLogger("linuxpilot.api.auth")

auth_router = APIRouter(prefix="/api/auth", tags=["authorization"])


class ApproveRequest(BaseModel):
    operation_id: str = Field(..., description="The authorization ticket ID to approve")
    action: Optional[str] = Field(None, description="Optional bound action verification")
    target_resource: Optional[str] = Field(None, description="Optional bound target resource verification")
    parameters: Optional[dict[str, Any]] = Field(None, description="Optional bound parameters verification")
    expected_postconditions: Optional[dict[str, Any]] = Field(
        None, description="Optional bound postconditions verification"
    )


class ApproveResponse(BaseModel):
    success: bool
    operation_id: str
    status: str
    reason: str
    authorization: Optional[AuthorizationPreview] = None


class RevokeRequest(BaseModel):
    operation_id: str = Field(..., description="The authorization ticket ID to revoke")
    reason: Optional[str] = Field("Revoked by user", description="Reason for revocation")


class RevokeResponse(BaseModel):
    success: bool
    operation_id: str
    status: str
    reason: str


@auth_router.post("/approve", response_model=ApproveResponse)
def approve_ticket(payload: ApproveRequest) -> ApproveResponse:
    """
    Explicitly transitions a PENDING authorization ticket to APPROVED.
    A generated preview or pending ticket does NOT constitute user approval;
    execution requires an APPROVED ticket.
    """
    decision = auth_manager.approve_authorization(
        operation_id=payload.operation_id,
        action=payload.action,
        target_resource=payload.target_resource,
        parameters=payload.parameters,
        expected_postconditions=payload.expected_postconditions,
    )

    preview = (
        auth_manager.to_preview(decision.authorization)
        if decision.authorization
        else None
    )

    return ApproveResponse(
        success=decision.is_authorized,
        operation_id=payload.operation_id,
        status=decision.authorization.status.value if decision.authorization else "UNKNOWN",
        reason=decision.reason,
        authorization=preview,
    )


@auth_router.post("/revoke", response_model=RevokeResponse)
def revoke_ticket(payload: RevokeRequest) -> RevokeResponse:
    """
    Revokes an authorization ticket so it can never be approved or executed.
    """
    decision = auth_manager.revoke_authorization(
        operation_id=payload.operation_id,
        reason=payload.reason or "Revoked by user",
    )
    return RevokeResponse(
        success=decision.is_authorized,
        operation_id=payload.operation_id,
        status=decision.authorization.status.value if decision.authorization else "UNKNOWN",
        reason=decision.reason,
    )


@auth_router.get("/{operation_id}", response_model=AuthorizationPreview)
def get_ticket_status(operation_id: str) -> AuthorizationPreview:
    """
    Retrieves the current preview, bounds, and status of an authorization ticket.
    """
    auth = auth_manager.get_authorization(operation_id)
    if not auth:
        raise HTTPException(status_code=404, detail=f"Authorization ticket '{operation_id}' not found.")
    return auth_manager.to_preview(auth)
