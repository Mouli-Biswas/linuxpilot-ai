"""
test_intent_classifier.py
-------------------------
Tests for deterministic intent classification and parameter extraction
across all 6 supported intents, slot filling, and fallback resilience.
"""

import asyncio
import pytest
from backend.ai.intent_classifier import intent_classifier
from backend.ai.schemas import Intent


def _classify(query: str):
    return asyncio.run(intent_classifier.classify(query))


def test_diagnostics_classification_and_resources():
    cases = [
        ("Why is my computer running slowly?", "overall"),
        ("check CPU", "cpu"),
        ("check CPU usage", "cpu"),
        ("system load", "cpu"),
        ("check RAM", "memory"),
        ("RAM usage", "memory"),
        ("memory usage", "memory"),
        ("disk space", "disk"),
        ("disk usage", "disk"),
        ("network status", "network"),
    ]
    for q, expected_resource in cases:
        res = _classify(q)
        assert res.intent == Intent.DIAGNOSTICS, f"Failed for query: {q}"
        assert res.confidence >= 0.90
        assert res.parameters.resource == expected_resource, f"Expected resource {expected_resource} for {q}"


def test_file_search_classification_and_slots():
    # 1. General large files
    res = _classify("Find all large files in my home directory")
    assert res.intent == Intent.FILE_SEARCH
    assert res.parameters.search_path == "~"
    assert res.parameters.min_size_mb == 100.0

    # 2. Python files > 50MB
    res = _classify("Find Python files larger than 50 MB in my home directory")
    assert res.intent == Intent.FILE_SEARCH
    assert res.parameters.file_type == "python"
    assert res.parameters.min_size_mb == 50.0

    # 3. PDF in Downloads
    res = _classify("Find PDF files in Downloads")
    assert res.intent == Intent.FILE_SEARCH
    assert res.parameters.file_type == "pdf"
    assert res.parameters.search_path == "~/Downloads"

    # 4. PDF in Documents
    res_docs = _classify("Find PDF files in Documents")
    assert res_docs.intent == Intent.FILE_SEARCH
    assert res_docs.parameters.file_type == "pdf"
    assert res_docs.parameters.search_path == "~/Documents"

    # 5. Units parsing: GB and KB
    res_gb = _classify("Find files larger than 2 GB")
    assert res_gb.intent == Intent.FILE_SEARCH
    assert res_gb.parameters.min_size_mb == 2048.0

    res_kb = _classify("Find files larger than 500 KB")
    assert res_kb.intent == Intent.FILE_SEARCH
    assert res_kb.parameters.min_size_mb is not None
    assert 0.4 < res_kb.parameters.min_size_mb < 0.6


def test_service_management_classification_and_slots():
    # Status
    res = _classify("Show me the status of nginx")
    assert res.intent == Intent.SERVICE_MANAGEMENT
    assert res.parameters.service_name == "nginx"
    assert res.parameters.action == "status"

    # Is docker running
    res_running = _classify("is docker running")
    assert res_running.intent == Intent.SERVICE_MANAGEMENT
    assert res_running.parameters.service_name == "docker"
    assert res_running.parameters.action == "status"

    # Restart
    res_restart = _classify("restart postgresql")
    assert res_restart.intent == Intent.SERVICE_MANAGEMENT
    assert res_restart.parameters.service_name == "postgresql"
    assert res_restart.parameters.action == "restart"

    # Start
    res_start = _classify("start nginx")
    assert res_start.intent == Intent.SERVICE_MANAGEMENT
    assert res_start.parameters.service_name == "nginx"
    assert res_start.parameters.action == "start"

    # Stop
    res_stop = _classify("stop apache")
    assert res_stop.intent == Intent.SERVICE_MANAGEMENT
    assert res_stop.parameters.service_name == "apache2"
    assert res_stop.parameters.action == "stop"


def test_log_analysis_classification_and_slots():
    res = _classify("Show recent system errors")
    assert res.intent == Intent.LOG_ANALYSIS
    assert res.parameters.log_source == "journalctl"
    assert res.parameters.log_filter == "error"

    res_dmesg = _classify("kernel logs in dmesg")
    assert res_dmesg.intent == Intent.LOG_ANALYSIS
    assert res_dmesg.parameters.log_source == "dmesg"

    res_nginx_logs = _classify("journalctl for nginx")
    assert res_nginx_logs.intent == Intent.LOG_ANALYSIS
    assert res_nginx_logs.parameters.log_source == "journalctl"
    assert res_nginx_logs.parameters.log_filter == "nginx"


def test_learning_mode_classification():
    res = _classify("Explain what chmod 755 means")
    assert res.intent == Intent.LEARNING_MODE
    assert res.parameters.command_or_concept == "chmod 755"

    res_df = _classify("what does df -h do")
    assert res_df.intent == Intent.LEARNING_MODE
    assert "df -h" in res_df.parameters.command_or_concept

    res_grep = _classify("how does grep work")
    assert res_grep.intent == Intent.LEARNING_MODE
    assert "grep" in res_grep.parameters.command_or_concept


def test_command_execution_classification():
    res_df = _classify("df -h")
    assert res_df.intent == Intent.COMMAND_EXECUTION
    assert res_df.parameters.raw_command == "df -h"

    res_run_df = _classify("run df -h")
    assert res_run_df.intent == Intent.COMMAND_EXECUTION
    assert res_run_df.parameters.raw_command == "df -h"

    res_apt = _classify("Run apt update")
    assert res_apt.intent == Intent.COMMAND_EXECUTION
    assert res_apt.parameters.raw_command == "apt update"

    res_htop = _classify("install htop")
    assert res_htop.intent == Intent.COMMAND_EXECUTION
    assert res_htop.parameters.raw_command == "install htop"

    res_ps = _classify("execute ps aux")
    assert res_ps.intent == Intent.COMMAND_EXECUTION
    assert res_ps.parameters.raw_command == "ps aux"


def test_empty_query_raises_value_error():
    with pytest.raises(ValueError):
        _classify("   ")
