import asyncio
import time
from backend.agent.orchestrator import orchestrator

queries = [
    ("Why is my computer running slowly?", False),
    ("Find all large files in my home directory", False),
    ("Find Python files larger than 50 MB in my home directory", False),
    ("Show me the status of nginx", False),
    ("Show recent system errors", False),
    ("Explain what chmod 755 means", False),
    ("df -h", False),
    ("systemctl restart nginx", False),
    ("rm -rf /", False),
]

print(f"{'QUERY':<58} | {'INTENT':<18} | {'CLASSIFY':<8} | {'PLAN':<5} | {'TOOL':<6} | {'SUMM':<5} | {'TOTAL':<7}")
print("-" * 118)

for q, conf in queries:
    t0 = time.perf_counter()
    r = asyncio.run(orchestrator.run(q, confirmed=conf))
    dt_ms = (time.perf_counter() - t0) * 1000
    t = r.timings
    print(f"{q:<58} | {r.intent:<18} | {t.classification_ms:6d}ms | {t.planning_ms:3d}ms | {t.tool_execution_ms:4d}ms | {t.summarization_ms:3d}ms | {r.total_duration_ms:5d}ms")
