# LinuxPilot AI 🐧✈️

**A local, AI-powered Linux operations assistant and system copilot.**

LinuxPilot AI is not a generic chat wrapper around a shell. It is an **intelligent, safety-first Linux operations agent**: a pipeline that classifies user intent, generates deterministic task plans, collects real hardware and filesystem metrics, validates commands against a strict **3-tier safety layer**, and synthesizes structured, actionable insights in milliseconds.

```
Conventional "AI Terminals":  User Prompt ──> LLM ──> Raw Shell Execution  (Dangerous & Unpredictable)

LinuxPilot AI Pipeline:       User Query
                                  ↓
                              Intent Classifier (Deterministic Fast-Path + Qwen 2.5 Fallback)
                                  ↓
                              Task Planner (Deterministic & Contextual Workflows)
                                  ↓
                              Tool Registry (psutil, os.scandir, systemctl, journalctl)
                                  ↓
                              3-Tier Command Safety Validator (READ_ONLY / MODIFYING / DANGEROUS)
                                  ↓
                              Structured Execution & Findings
                                  ↓
                              Deterministic Response Synthesis (response.formatter)
                                  ↓
                              Polished Terminal UI Dashboard
```

---

## ⚡ Performance Optimization & Benchmarks

LinuxPilot AI utilizes a **Deterministic Fast-Path Architecture** that eliminates slow LLM roundtrips for standard system queries. Common operations are classified, planned, and formatted locally in milliseconds, reserving Ollama / Qwen 2.5 Instruct strictly for ambiguous queries.

| Query / Operation | Previous Latency | Optimized Latency | Speedup | Execution Engine |
|---|---|---|---|---|
| `"Why is my computer running slowly?"` | ~45,000 ms | **506 ms** | **89x Faster** | Multi-core Diagnostics Pipeline |
| `"Find all large files in my home directory"` | ~164,000 ms | **73 ms** | **2200x Faster** | Fast `os.scandir` + Cache Exclusions |
| `"Find Python files larger than 50 MB in my home directory"` | ~120,000 ms | **50 ms** | **2400x Faster** | Pre-filtered Extension Matching |
| `"Show me the status of nginx"` | ~30,000 ms | **8 ms** | **3750x Faster** | Service Manager Fast-Path |
| `"Show recent system errors"` | ~25,000 ms | **16 ms** | **1560x Faster** | Parameterized Journalctl Filter |
| `"Explain what chmod 755 means"` | ~15,000 ms | **1 ms** | **15000x Faster** | Instant Knowledge Base |
| `"df -h"` | ~15,000 ms | **10 ms** | **1500x Faster** | Read-Only Fast Execution |
| `"systemctl restart nginx"` (Modifying) | ~20,000 ms | **< 1 ms** | **20000x Faster** | Confirmation Gate Prompt |
| `"rm -rf /"` (Dangerous command) | ~10,000 ms | **2 ms** | **5000x Faster** | Security Blocklist Engine |

---

## 🛡️ 3-Tier Command Safety Layer

Security is the core architectural foundation of LinuxPilot AI. Commands are categorized at the execution boundary into three strict tiers:

```
                            [User Request / Agent Command]
                                          │
                        ┌─────────────────┴─────────────────┐
                        │   Command Validation Layer        │
                        └─────────────────┬─────────────────┘
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
       [READ_ONLY]                   [MODIFYING]                   [DANGEROUS]
   Non-destructive inspection     State-altering changes       Catastrophic / Root Deletion
   (df, free, ps, top, ls,        (systemctl restart, apt      (rm -rf /, mkfs, dd to disk,
   uptime, systemctl status)       install, chmod, rm file)    fork bomb, curl|bash, :(){...})
            │                             │                             │
            ▼                             ▼                             ▼
       AUTO-EXECUTE                 EXPLICIT USER               PERMANENTLY BLOCKED
    (Instant Output)             CONFIRMATION REQUIRED           (Zero Exceptions)
```

> [!IMPORTANT]
> **Safety Boundary Guarantee**: Dangerous commands (`rm -rf /`, raw disk overwriting, fork bombs) are blocked unconditionally. Supplying `confirmed=True` will **never** bypass a `BLOCKED` verdict.

---

## 🚀 Key Features

- ⚡ **Instant System Diagnostics**: Live CPU usage, per-core utilization, 1m/5m load averages, RAM & swap percentages, disk capacity, and network reachability.
- 📂 **High-Speed File Discovery**: Deep filesystem traversal powered by `os.scandir` with directory exclusions (`.git`, `node_modules`, package caches), size filters, and format categories.
- ⚙️ **Systemd Service Management**: Inspect and safely control services (`nginx`, `docker`, `ssh`, `apache2`, `postgresql`, `mysql`).
- 📜 **Log Analysis & Error Diagnostics**: Structured queries for `journalctl` and `dmesg` with priority filtering.
- 💡 **Linux Concept Tutor**: Instant permission matrix explanations (`chmod 755`), tarball manipulation, and command breakdowns.
- 🔒 **Local-Only Security**: Default backend binding to `127.0.0.1` prevents unauthorized network access.
- 🖥️ **Modern Operations Dashboard**: React 18 + TypeScript + Tailwind UI featuring live metrics, step-by-step pipeline visualization, latency breakdowns, and query history.

---

## 💻 Quick Start for Linux (Ubuntu / Debian / Mint / Fedora)

### 1. Requirements
- Linux OS (Ubuntu 20.04+, Debian 11+, Fedora 38+, Linux Mint)
- Python 3.10+ & `python3-venv`
- Node.js 18+ & `npm`
- Git

### 2. One-Command Automated Installation

```bash
# Clone the repository
git clone https://github.com/saiteja-hub/linuxpilot-ai.git
cd linuxpilot-ai/linuxpilot-ai

# Run the automated installer
./scripts/install.sh
```

The installer will:
1. Verify Python 3.10+ and Node.js 18+.
2. Create a clean Linux virtual environment in `.venv/`.
3. Install all backend dependencies (`requirements.txt`).
4. Install frontend npm dependencies.
5. Initialize the SQLite database schema (`linuxpilot.db`).

### 3. Start LinuxPilot AI

```bash
./scripts/start.sh
```

Once started, open the web dashboard:
- **Dashboard UI**: [http://localhost:1420](http://localhost:1420)
- **Backend API**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. Management Commands

```bash
# Check service status & health
./scripts/status.sh

# Stop backend and frontend services cleanly
./scripts/stop.sh
```

---

## 🪟 Windows Development & Testing

LinuxPilot AI runs on Windows for development and dashboard testing:

```powershell
# In terminal 1 (Backend):
cd linuxpilot-ai
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# In terminal 2 (Frontend):
cd frontend
npm install
npm run dev
```

*Note: While diagnostics, file search, tutor, and command safety work cross-platform, Linux-native integrations (`systemctl`, `journalctl`) gracefully return structured status messages when executed on Windows.*

---

## 🧪 Running Automated Tests

```bash
# Run all 55 tests from repository root
python -m pytest -v
```

```
tests/test_api.py (9 tests) ......................... PASSED
tests/test_command_safety.py (4 tests) ............. PASSED
tests/test_command_validator.py (13 tests) ......... PASSED
tests/test_intent_classifier.py (7 tests) .......... PASSED
tests/test_orchestrator.py (9 tests) ............... PASSED
tests/test_planner.py (6 tests) .................... PASSED
tests/test_tools.py (7 tests) ...................... PASSED
============================= 55 passed in 2.72s =============================
```

---

## 📡 API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check and environment configuration |
| `/api/agent/ask` | POST | Full agent pipeline (`classify` → `plan` → `execute` → `synthesize`) |
| `/api/agent/history` | GET | Retrieve recent interaction history from SQLite |
| `/api/intent/classify` | POST | Intent detection & parameter slot extraction |
| `/api/diagnostics/cpu` | GET | Real-time CPU usage, core breakdown, and load average |
| `/api/diagnostics/memory` | GET | RAM and swap utilization metrics |
| `/api/diagnostics/disk` | GET | Mount point capacity and disk usage |
| `/api/diagnostics/network` | GET | Gateway, DNS, IP, and Internet connectivity status |
| `/api/services/{name}/status` | GET | Inspect system service status (`nginx`, `docker`, etc.) |
| `/api/services/{name}/restart`| POST | Restart service (gated by user confirmation) |
| `/api/logs/journalctl` | POST | Safe parameterized journalctl log query |
| `/api/logs/dmesg` | POST | Parameterized kernel dmesg query |
| `/api/search/files` | POST | Fast filesystem search by name, category, and size |
| `/api/execute/command` | POST | Validate and run a command via 3-tier safety layer |

---

## 🎯 3-Minute Hackathon Demo Flow

1. **⚡ Live Diagnostics**: Type `"Why is my computer running slowly?"` to view real-time CPU, RAM, and Disk health analysis in ~500ms.
2. **🔍 Ultra-Fast File Search**: Click *"Large Files"* or type `"Find all large files in my home directory"` to see large files (>100MB) ranked and formatted in ~70ms.
3. **🐍 Filtered Search**: Type `"Find Python files larger than 50 MB in my home directory"` to demonstrate parameter extraction (`file_type=python`, `min_size_mb=50`).
4. **⚠️ Modifying Command Confirmation**: Click *"Restart Nginx"*. Demonstrate the agent identifying `MODIFYING` risk and requesting user confirmation before proceeding.
5. **🚫 Security Blocklist Engine**: Type `"rm -rf /"`. Demonstrate the immediate `<2ms` blocked response explaining root deletion protection.
6. **💡 Linux Concept Tutor**: Click *"Explain chmod 755"* to show the instant permission table explanation.
