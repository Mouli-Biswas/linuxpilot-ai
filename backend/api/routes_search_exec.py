"""
routes_search_exec.py
-----------------------
FastAPI endpoints for FILE_SEARCH and COMMAND_EXECUTION intents. The
execute endpoint always routes through the Command Validation Layer —
there is no code path in this API that runs a raw string directly.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from backend.search.file_search import FileSearchQuery, FileSearchResult, search_files
from backend.validator.command_validator import ExecutionResult, execute_validated_command

logger = logging.getLogger("linuxpilot.api.search_exec")

search_router = APIRouter(prefix="/api/search", tags=["file_search"])
exec_router = APIRouter(prefix="/api/execute", tags=["command_execution"])


@search_router.post("/files", response_model=FileSearchResult)
def search_files_endpoint(query: FileSearchQuery) -> FileSearchResult:
    return search_files(query)


class CommandExecutionRequest(BaseModel):
    command: str
    confirmed: bool = False


@exec_router.post("/command", response_model=ExecutionResult)
def execute_command_endpoint(payload: CommandExecutionRequest) -> ExecutionResult:
    return execute_validated_command(payload.command, confirmed=payload.confirmed)

