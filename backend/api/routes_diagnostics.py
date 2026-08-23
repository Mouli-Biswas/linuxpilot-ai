"""
routes_diagnostics.py
----------------------
FastAPI endpoints wrapping backend.diagnostics.diagnostics. Every
endpoint returns a uniform {success, data, error} envelope so the
frontend never has to branch on status codes for expected failure
modes (e.g. a mount point that doesn't exist).
"""

from __future__ import annotations

import logging
from typing import Generic, Optional, TypeVar

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.diagnostics.diagnostics import (
    CPUMetrics,
    DiagnosticsError,
    DiskMetrics,
    MemoryMetrics,
    NetworkMetrics,
    get_cpu_metrics,
    get_disk_metrics,
    get_memory_metrics,
    get_network_metrics,
)

logger = logging.getLogger("linuxpilot.api.diagnostics")
router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """Pydantic v2 generic response envelope: {success, data, error}."""

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None


@router.get("/cpu", response_model=Envelope[CPUMetrics])
def cpu_diagnostics(
    sample_seconds: float = Query(0.5, ge=0.1, le=3.0, description="CPU sampling window in seconds")
) -> Envelope[CPUMetrics]:
    try:
        return Envelope(success=True, data=get_cpu_metrics(sample_seconds=sample_seconds))
    except DiagnosticsError as exc:
        logger.error("CPU diagnostics failed: %s", exc)
        return Envelope(success=False, error=str(exc))


@router.get("/memory", response_model=Envelope[MemoryMetrics])
def memory_diagnostics() -> Envelope[MemoryMetrics]:
    try:
        return Envelope(success=True, data=get_memory_metrics())
    except DiagnosticsError as exc:
        logger.error("Memory diagnostics failed: %s", exc)
        return Envelope(success=False, error=str(exc))


@router.get("/disk", response_model=Envelope[DiskMetrics])
def disk_diagnostics(
    mount_point: str = Query("/", description="Filesystem mount point to inspect"),
    scan_path: Optional[str] = Query(None, description="Optional path to scan for largest folders/files"),
    top_n: int = Query(5, ge=1, le=25),
    min_size_mb: float = Query(0.0, ge=0.0, description="Minimum file size filter in MB"),
    name_filter: Optional[str] = Query(None, description="Substring filter on filename"),
) -> Envelope[DiskMetrics]:
    try:
        data = get_disk_metrics(
            mount_point=mount_point,
            scan_path=scan_path,
            top_n=top_n,
            min_size_mb=min_size_mb,
            name_filter=name_filter,
        )
        return Envelope(success=True, data=data)
    except DiagnosticsError as exc:
        logger.error("Disk diagnostics failed: %s", exc)
        return Envelope(success=False, error=str(exc))


@router.get("/network", response_model=Envelope[NetworkMetrics])
def network_diagnostics() -> Envelope[NetworkMetrics]:
    try:
        return Envelope(success=True, data=get_network_metrics())
    except DiagnosticsError as exc:
        logger.error("Network diagnostics failed: %s", exc)
        return Envelope(success=False, error=str(exc))
