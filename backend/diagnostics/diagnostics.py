"""
diagnostics.py
---------------
Collects CPU, memory, disk, and network diagnostics using psutil (plus
a few thin subprocess calls for things psutil doesn't cover, like DNS
resolver config). Every public function returns a Pydantic model so the
FastAPI layer can serialize it directly and callers get validated,
typed data instead of ad-hoc dicts.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
from pathlib import Path
from typing import Optional

import psutil
from pydantic import BaseModel, Field

logger = logging.getLogger("linuxpilot.diagnostics")


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------
class CPUMetrics(BaseModel):
    usage_percent: float
    per_core_percent: list[float]
    core_count_logical: int
    core_count_physical: Optional[int]
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float
    temperature_celsius: Optional[float] = Field(
        None, description="Highest reported sensor temp, if the platform exposes it."
    )


class MemoryMetrics(BaseModel):
    total_mb: float
    available_mb: float
    used_mb: float
    used_percent: float
    cached_mb: float
    swap_total_mb: float
    swap_used_mb: float
    swap_percent: float


class LargeEntry(BaseModel):
    path: str
    size_mb: float


class DiskMetrics(BaseModel):
    mount_point: str
    total_gb: float
    used_gb: float
    free_gb: float
    used_percent: float
    largest_folders: list[LargeEntry] = Field(default_factory=list)
    largest_files: list[LargeEntry] = Field(default_factory=list)


class NetworkMetrics(BaseModel):
    internet_connected: bool
    local_ip: Optional[str]
    default_gateway: Optional[str]
    dns_servers: list[str]
    bytes_sent_mb: float
    bytes_recv_mb: float


class DiagnosticsError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------
def get_cpu_metrics(sample_seconds: float = 0.5) -> CPUMetrics:
    try:
        usage = psutil.cpu_percent(interval=sample_seconds)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        logical = psutil.cpu_count(logical=True) or 0
        physical = psutil.cpu_count(logical=False)

        try:
            load1, load5, load15 = os.getloadavg()
        except (AttributeError, OSError):
            load1 = load5 = load15 = 0.0

        temp = _read_cpu_temperature()

        return CPUMetrics(
            usage_percent=usage,
            per_core_percent=per_core,
            core_count_logical=logical,
            core_count_physical=physical,
            load_avg_1m=round(load1, 2),
            load_avg_5m=round(load5, 2),
            load_avg_15m=round(load15, 2),
            temperature_celsius=temp,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to collect CPU metrics")
        raise DiagnosticsError(f"CPU metrics collection failed: {exc}") from exc


def _read_cpu_temperature() -> Optional[float]:
    """Best-effort temperature read; not all systems/containers expose sensors."""
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    if not temps:
        return None
    highest: Optional[float] = None
    for entries in temps.values():
        for entry in entries:
            if entry.current and (highest is None or entry.current > highest):
                highest = entry.current
    return highest


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
def get_memory_metrics() -> MemoryMetrics:
    try:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return MemoryMetrics(
            total_mb=round(vm.total / 1024 / 1024, 1),
            available_mb=round(vm.available / 1024 / 1024, 1),
            used_mb=round(vm.used / 1024 / 1024, 1),
            used_percent=vm.percent,
            cached_mb=round(getattr(vm, "cached", 0) / 1024 / 1024, 1),
            swap_total_mb=round(swap.total / 1024 / 1024, 1),
            swap_used_mb=round(swap.used / 1024 / 1024, 1),
            swap_percent=swap.percent,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to collect memory metrics")
        raise DiagnosticsError(f"Memory metrics collection failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------
def get_disk_metrics(
    mount_point: str = "/",
    scan_path: Optional[str] = None,
    top_n: int = 5,
    min_size_mb: float = 0.0,
    name_filter: Optional[str] = None,
) -> DiskMetrics:
    try:
        usage = psutil.disk_usage(mount_point)
        base = DiskMetrics(
            mount_point=mount_point,
            total_gb=round(usage.total / 1024**3, 2),
            used_gb=round(usage.used / 1024**3, 2),
            free_gb=round(usage.free / 1024**3, 2),
            used_percent=usage.percent,
        )
        if scan_path:
            base.largest_folders = _largest_folders(scan_path, top_n)
            base.largest_files = _largest_files(scan_path, top_n, min_size_mb, name_filter)
        return base
    except FileNotFoundError as exc:
        raise DiagnosticsError(f"Mount point or path not found: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to collect disk metrics")
        raise DiagnosticsError(f"Disk metrics collection failed: {exc}") from exc


def _largest_folders(root: str, top_n: int) -> list[LargeEntry]:
    root_path = Path(root)
    if not root_path.exists():
        return []
    sizes: list[LargeEntry] = []
    try:
        for entry in root_path.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                total = _dir_size_bytes(entry)
                sizes.append(LargeEntry(path=str(entry), size_mb=round(total / 1024 / 1024, 2)))
    except PermissionError:
        pass
    sizes.sort(key=lambda e: e.size_mb, reverse=True)
    return sizes[:top_n]


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            try:
                if f.is_file() and not f.is_symlink():
                    total += f.stat().st_size
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    return total


def _largest_files(
    root: str, top_n: int, min_size_mb: float, name_filter: Optional[str]
) -> list[LargeEntry]:
    root_path = Path(root)
    if not root_path.exists():
        return []
    results: list[LargeEntry] = []
    try:
        for f in root_path.rglob("*"):
            try:
                if not f.is_file() or f.is_symlink():
                    continue
                if name_filter and name_filter.lower() not in f.name.lower():
                    continue
                size_mb = f.stat().st_size / 1024 / 1024
                if size_mb < min_size_mb:
                    continue
                results.append(LargeEntry(path=str(f), size_mb=round(size_mb, 2)))
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    results.sort(key=lambda e: e.size_mb, reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
def get_network_metrics(check_host: str = "8.8.8.8", check_port: int = 53, timeout: float = 2.0) -> NetworkMetrics:
    try:
        connected = _check_internet(check_host, check_port, timeout)
        local_ip = _get_local_ip()
        gateway = _get_default_gateway()
        dns_servers = _get_dns_servers()
        counters = psutil.net_io_counters()

        return NetworkMetrics(
            internet_connected=connected,
            local_ip=local_ip,
            default_gateway=gateway,
            dns_servers=dns_servers,
            bytes_sent_mb=round(counters.bytes_sent / 1024 / 1024, 2),
            bytes_recv_mb=round(counters.bytes_recv / 1024 / 1024, 2),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to collect network metrics")
        raise DiagnosticsError(f"Network metrics collection failed: {exc}") from exc


def _check_internet(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get_local_ip() -> Optional[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _get_default_gateway() -> Optional[str]:
    """Parses `ip route show default` — read-only, no injection risk (no user input)."""
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _get_dns_servers() -> list[str]:
    servers: list[str] = []
    resolv_conf = Path("/etc/resolv.conf")
    if resolv_conf.exists():
        try:
            for line in resolv_conf.read_text().splitlines():
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        servers.append(parts[1])
        except OSError:
            pass
    return servers
