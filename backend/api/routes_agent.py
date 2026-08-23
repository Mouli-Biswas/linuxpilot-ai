"""
routes_agent.py
----------------
The single "ask LinuxPilot AI anything" endpoint that drives the full
classify -> plan -> execute -> summarize agent loop, plus an endpoint
for querying interaction history.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.agent.orchestrator import AgentRunResult, orchestrator
from backend.database.db import get_recent_interactions, log_interaction

logger = logging.getLogger("linuxpilot.api.agent")
router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language user query")
    confirmed: bool = Field(False, description="Explicit confirmation flag for modifying commands")


class AgentQueryResponse(BaseModel):
    success: bool
    result: AgentRunResult | None = None
    error: str | None = None


class InteractionHistoryItem(BaseModel):
    id: int
    query: str
    intent: str
    final_answer: str
    duration_ms: int
    created_at: str


class HistoryResponse(BaseModel):
    success: bool
    history: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


@router.post("/ask", response_model=AgentQueryResponse)
async def ask_agent(payload: AgentQueryRequest) -> AgentQueryResponse:
    query_str = payload.query.strip()
    if not query_str:
        return AgentQueryResponse(success=False, error="Query must not be empty.")

    try:
        result = await orchestrator.run(query_str, confirmed=payload.confirmed)
        log_interaction(
            query=query_str,
            intent=result.intent,
            final_answer=result.final_answer,
            duration_ms=result.total_duration_ms,
        )
        return AgentQueryResponse(success=True, result=result)
    except Exception as exc:  # noqa: BLE001 - top-level API boundary
        logger.exception("Agent run failed")
        return AgentQueryResponse(success=False, error=str(exc))


@router.get("/history", response_model=HistoryResponse)
def get_history(limit: int = Query(20, ge=1, le=100)) -> HistoryResponse:
    try:
        rows = get_recent_interactions(limit=limit)
        return HistoryResponse(success=True, history=rows)
    except Exception as exc:
        logger.exception("Failed to retrieve interaction history")
        return HistoryResponse(success=False, error=str(exc))
