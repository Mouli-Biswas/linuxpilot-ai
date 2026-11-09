"""
test_api.py
-----------
Tests all FastAPI REST endpoints:
- GET /api/health
- POST /api/agent/ask
- GET /api/agent/history
- POST /api/intent/classify
- GET /api/diagnostics/cpu, memory, disk, network
- GET /api/services/{service_name}/status
- POST /api/search/files
- POST /api/execute/command
"""

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "ollama_model" in data


def test_agent_ask_diagnostics():
    resp = client.post("/api/agent/ask", json={"query": "Why is my computer running slowly?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["intent"] == "DIAGNOSTICS"
    assert "System Diagnostics Report" in data["result"]["final_answer"]


def test_agent_ask_empty_query():
    resp = client.post("/api/agent/ask", json={"query": "   "})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "empty" in data["error"].lower()


def test_agent_history():
    resp = client.get("/api/agent/history?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["history"], list)


def test_intent_classify_endpoint():
    resp = client.post("/api/intent/classify", json={"query": "Find PDF files in Downloads"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["intent"] == "FILE_SEARCH"


def test_diagnostics_endpoints():
    cpu = client.get("/api/diagnostics/cpu?sample_seconds=0.1")
    assert cpu.status_code == 200
    assert cpu.json()["success"] is True

    mem = client.get("/api/diagnostics/memory")
    assert mem.status_code == 200
    assert mem.json()["success"] is True

    disk = client.get("/api/diagnostics/disk")
    assert disk.status_code == 200
    assert disk.json()["success"] is True

    net = client.get("/api/diagnostics/network")
    assert net.status_code == 200
    assert net.json()["success"] is True


def test_services_endpoint():
    resp = client.get("/api/services/nginx/status")
    assert resp.status_code == 200
    assert resp.json()["service"] == "nginx"


def test_search_files_endpoint():
    resp = client.post("/api/search/files", json={"search_path": ".", "file_type": "python"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["match_count"] > 0


def test_execute_command_endpoint_safety():
    # Dangerous command should be blocked
    resp_danger = client.post("/api/execute/command", json={"command": "rm -rf /"})
    assert resp_danger.status_code == 200
    assert resp_danger.json()["validation"]["verdict"] == "BLOCKED"

    # Modifying command requires action-bound authorization
    resp_mod = client.post("/api/execute/command", json={"command": "apt install nginx", "confirmed": False})
    assert resp_mod.status_code == 200
    data = resp_mod.json()
    assert data["requires_confirmation"] is True
    assert data["executed"] is False
    assert data["authorization"] is not None
    assert data["authorization"]["operation_id"].startswith("op_auth_")
    assert data["authorization"]["action"] == "command.execute"

    # Client-sent confirmed=True alone without operation_id does not execute
    resp_bool = client.post("/api/execute/command", json={"command": "apt install nginx", "confirmed": True})
    assert resp_bool.status_code == 200
    assert resp_bool.json()["executed"] is False
    assert resp_bool.json()["requires_confirmation"] is True


def test_agent_ask_modifying_service_flow():
    # 1. Preview request creates PENDING ticket
    resp = client.post("/api/agent/ask", json={"query": "systemctl restart nginx", "confirmed": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    result = data["result"]
    assert result["requires_confirmation"] is True
    assert result["pending_authorization"] is not None
    op_id = result["pending_authorization"]["operation_id"]
    assert result["pending_authorization"]["action"] == "service.restart"
    assert result["pending_authorization"]["target_resource"] == "service:nginx"
    assert "User Confirmation Required" in result["final_answer"]

    # 2. Executing while PENDING must fail (no implicit approval)
    resp_pending = client.post("/api/agent/ask", json={"query": "systemctl restart nginx", "confirmed": True, "operation_id": op_id})
    assert resp_pending.status_code == 200
    data_pending = resp_pending.json()
    assert data_pending["success"] is True
    # The step execution for service.restart should reflect authorization rejection
    step_res = data_pending["result"]["step_results"][0]["output"]
    assert step_res["success"] is False
    assert "not been approved" in step_res["error"].lower()

    # 3. Explicit approval via dedicated endpoint
    resp_approve = client.post("/api/auth/approve", json={"operation_id": op_id})
    assert resp_approve.status_code == 200
    assert resp_approve.json()["status"] == "APPROVED"

    # 4. Executing with APPROVED ticket succeeds
    from dataclasses import replace
    from unittest.mock import patch
    import subprocess
    from backend.utils.config import settings

    patched_settings = replace(settings, ALLOW_COMMAND_EXECUTION=True)
    with patch("backend.validator.command_validator.settings", patched_settings), \
         patch("backend.services.service_manager.settings", patched_settings), \
         patch("backend.services.service_manager._run_systemctl") as mock_sys:
        mock_sys.side_effect = [
            subprocess.CompletedProcess(args=["systemctl", "is-active", "nginx"], returncode=0, stdout="active", stderr=""),
            subprocess.CompletedProcess(args=["systemctl", "restart", "nginx"], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=["systemctl", "is-active", "nginx"], returncode=0, stdout="active", stderr=""),
        ]
        resp_exec = client.post(
            "/api/agent/ask",
            json={"query": "systemctl restart nginx", "confirmed": True, "operation_id": op_id},
        )
        assert resp_exec.status_code == 200
        step_exec = resp_exec.json()["result"]["step_results"][0]["output"]
        assert step_exec["success"] is True
        assert step_exec["postcondition_verified"] is True
