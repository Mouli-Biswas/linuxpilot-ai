"""
schemas.py
----------
Pydantic models shared by the intent classifier, the agent orchestrator,
and the FastAPI route layer. Keeping them here (rather than inline in
routes.py) means the AI layer and the API layer can both import the same
contract without circular imports.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field



class Intent(str, Enum):
    DIAGNOSTICS = "DIAGNOSTICS"
    FILE_SEARCH = "FILE_SEARCH"
    SERVICE_MANAGEMENT = "SERVICE_MANAGEMENT"
    LOG_ANALYSIS = "LOG_ANALYSIS"
    COMMAND_EXECUTION = "COMMAND_EXECUTION"
    LEARNING_MODE = "LEARNING_MODE"


class IntentParameters(BaseModel):
    """
    Free-form but documented slot-filling bag. Every field is optional
    because a single query only ever populates the ones relevant to its
    intent (e.g. FILE_SEARCH populates file_name/file_type/min_size_mb,
    SERVICE_MANAGEMENT populates service_name/action).
    """

    # DIAGNOSTICS
    resource: Optional[str] = Field(
        None, description="cpu | memory | disk | network | overall"
    )

    # FILE_SEARCH
    file_name: Optional[str] = Field(None, description="Filename or pattern to search for")
    file_type: Optional[str] = Field(None, description="Extension or category, e.g. pdf, image")
    min_size_mb: Optional[float] = Field(None, description="Minimum file size filter in MB")
    search_path: Optional[str] = Field(None, description="Root path to search under")

    # SERVICE_MANAGEMENT
    service_name: Optional[str] = Field(
        None, description="docker | apache2 | nginx | ssh | mysql | postgresql"
    )
    action: Optional[str] = Field(None, description="status | restart | start | stop")

    # LOG_ANALYSIS
    log_source: Optional[str] = Field(None, description="journalctl | dmesg | syslog")
    log_filter: Optional[str] = Field(None, description="Unit name, priority, or keyword filter")
    time_range: Optional[str] = Field(None, description="e.g. 'last 1 hour', 'today'")

    # COMMAND_EXECUTION
    raw_command: Optional[str] = Field(None, description="The literal command the user wants run")

    # LEARNING_MODE
    command_or_concept: Optional[str] = Field(
        None, description="The command or concept the user wants explained"
    )

    model_config = ConfigDict(extra="allow")



class ClassificationResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    parameters: IntentParameters
    raw_query: str
    reasoning: Optional[str] = Field(
        None, description="Short model-provided rationale, useful for debugging/logging"
    )


class ClassifyRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language user query")


class ClassifyResponse(BaseModel):
    success: bool
    result: Optional[ClassificationResult] = None
    error: Optional[str] = None
