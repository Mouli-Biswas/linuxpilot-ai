"""
test_tools.py
-------------
Unit tests for core LinuxPilot AI tools: CPU, memory, disk, network,
file search, service manager, and log analysis.
"""

from backend.diagnostics.diagnostics import (
    get_cpu_metrics,
    get_disk_metrics,
    get_memory_metrics,
    get_network_metrics,
)
from backend.search.file_search import FileSearchQuery, search_files
from backend.services.service_manager import check_status
from backend.commands.log_analysis import JournalctlQuery, query_journalctl


def test_cpu_metrics():
    metrics = get_cpu_metrics(sample_seconds=0.1)
    assert metrics.usage_percent >= 0.0
    assert metrics.core_count_logical >= 1


def test_memory_metrics():
    metrics = get_memory_metrics()
    assert metrics.total_mb > 0
    assert 0 <= metrics.used_percent <= 100


def test_disk_metrics():
    metrics = get_disk_metrics(mount_point=".")
    assert metrics.total_gb > 0
    assert 0 <= metrics.used_percent <= 100


def test_network_metrics():
    metrics = get_network_metrics()
    assert isinstance(metrics.internet_connected, bool)


def test_file_search_local():
    # Search for python files in current directory
    res = search_files(FileSearchQuery(search_path=".", file_type="python"))
    assert res.match_count > 0
    assert any(m.path.endswith(".py") for m in res.matches)


def test_service_status_unknown_service_handled():
    # Attempting to check a service on non-Linux or without systemd returns structured result
    res = check_status("nginx")
    assert res.service == "nginx"
    assert isinstance(res.success, bool)


def test_journalctl_query_safety():
    # Safe query model validation
    q = JournalctlQuery(keyword="error", max_lines=10)
    assert q.keyword == "error"
    assert q.max_lines == 10
