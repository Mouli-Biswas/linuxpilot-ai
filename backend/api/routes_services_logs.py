"""
routes_services_logs.py
------------------------
FastAPI endpoints for service management (status/restart/start/stop)
and log analysis (journalctl/dmesg).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.commands.log_analysis import (
    DmesgQuery,
    JournalctlQuery,
    LogQueryError,
    LogQueryResult,
    query_dmesg,
    query_journalctl,
)
from backend.services.service_manager import (
    ServiceManagerError,
    ServiceResult,
    check_status,
    restart_service,
    start_service,
    stop_service,
)

logger = logging.getLogger("linuxpilot.api.services_logs")

services_router = APIRouter(prefix="/api/services", tags=["services"])
logs_router = APIRouter(prefix="/api/logs", tags=["logs"])


@services_router.get("/{service_name}/status", response_model=ServiceResult)
def service_status(service_name: str) -> ServiceResult:
    try:
        return check_status(service_name)
    except ServiceManagerError as exc:
        return ServiceResult(
            service=service_name, unit="", action="status", success=False, output="", error=str(exc)
        )


@services_router.post("/{service_name}/restart", response_model=ServiceResult)
def service_restart(service_name: str) -> ServiceResult:
    try:
        return restart_service(service_name)
    except ServiceManagerError as exc:
        return ServiceResult(
            service=service_name, unit="", action="restart", success=False, output="", error=str(exc)
        )


@services_router.post("/{service_name}/start", response_model=ServiceResult)
def service_start(service_name: str) -> ServiceResult:
    try:
        return start_service(service_name)
    except ServiceManagerError as exc:
        return ServiceResult(service=service_name, unit="", action="start", success=False, output="", error=str(exc))


@services_router.post("/{service_name}/stop", response_model=ServiceResult)
def service_stop(service_name: str) -> ServiceResult:
    try:
        return stop_service(service_name)
    except ServiceManagerError as exc:
        return ServiceResult(service=service_name, unit="", action="stop", success=False, output="", error=str(exc))


@logs_router.post("/journalctl", response_model=LogQueryResult)
def logs_journalctl(query: JournalctlQuery) -> LogQueryResult:
    try:
        return query_journalctl(query)
    except LogQueryError as exc:
        logger.warning("journalctl query rejected: %s", exc)
        return LogQueryResult(source="journalctl", query_summary=str(exc), entry_count=0, entries=[], truncated=False)


@logs_router.post("/dmesg", response_model=LogQueryResult)
def logs_dmesg(query: DmesgQuery) -> LogQueryResult:
    try:
        return query_dmesg(query)
    except LogQueryError as exc:
        logger.warning("dmesg query rejected: %s", exc)
        return LogQueryResult(source="dmesg", query_summary=str(exc), entry_count=0, entries=[], truncated=False)
