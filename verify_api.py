import os
import sys
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

queries = [
    "Why is my computer running slowly?",
    "Find all large files in my home directory",
    "df -h",
    "systemctl restart nginx",
    "rm -rf /",
]

for query in queries:
    resp = client.post("/api/agent/ask", json={"query": query})
    data = resp.json()
    res = data.get("result", {})
    print(f"=== QUERY: {query} ===")
    print(f"STATUS: {resp.status_code} | SUCCESS: {data.get('success')} | INTENT: {res.get('intent')} | TIME: {res.get('total_duration_ms')}ms")
    print("ANSWER:")
    print(res.get("final_answer"))
    print("-" * 60)
