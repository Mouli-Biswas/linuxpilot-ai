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

    # Modifying command requires confirmation
    resp_mod = client.post("/api/execute/command", json={"command": "apt install nginx", "confirmed": False})
    assert resp_mod.status_code == 200
    assert resp_mod.json()["requires_confirmation"] is True
