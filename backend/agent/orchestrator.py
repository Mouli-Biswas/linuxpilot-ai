"""
orchestrator.py
----------------
The AI Agent Orchestrator for LinuxPilot AI.

Pipeline:
    1. Classify intent (Deterministic fast-path / LLM fallback)
    2. Build execution plan (Deterministic contextual plan / LLM fallback)
    3. Execute tools sequentially with timing & error resilience
    4. Collect tool outputs
    5. Generate fast deterministic answer for structured tool outputs
    6. Use LLM summarizer only when natural language synthesis is required
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.agent.planner import Plan, PlanStep, task_planner
from backend.agent.summarizer import summarize
from backend.agent.tool_registry import run_tool
from backend.ai.intent_classifier import intent_classifier
from backend.ai.schemas import ClassificationResult

logger = logging.getLogger("linuxpilot.agent.orchestrator")


class StepExecution(BaseModel):
    step: int
    tool: str
    description: str
    output: dict[str, Any]
    duration_ms: int


class AgentTimings(BaseModel):
    classification_ms: int = 0
    planning_ms: int = 0
    tool_execution_ms: int = 0
    summarization_ms: int = 0
    total_ms: int = 0


class AgentRunResult(BaseModel):
    query: str
    intent: str
    confidence: float
    plan: list[PlanStep]
    step_results: list[StepExecution]
    final_answer: str
    total_duration_ms: int
    timings: Optional[AgentTimings] = None


# ---------------------------------------------------------------------------
# BUILT-IN KNOWLEDGE FOR INSTANT LEARNING MODE EXPLANATIONS
# ---------------------------------------------------------------------------
_LEARNING_KNOWLEDGE: dict[str, str] = {
    "chmod 755": (
        "**`chmod 755`** sets file/directory permissions to **`rwxr-xr-x`**:\n\n"
        "- **Owner (7 = 4+2+1)**: Read (`r`), Write (`w`), and Execute (`x`)\n"
        "- **Group (5 = 4+0+1)**: Read (`r`) and Execute (`x`)\n"
        "- **Others (5 = 4+0+1)**: Read (`r`) and Execute (`x`)\n\n"
        "**Usage:** This is the standard permission for scripts, programs, and directories in Linux, "
        "allowing all users to read and run them while preventing unauthorized modifications."
    ),
    "chmod 644": (
        "**`chmod 644`** sets file permissions to **`rw-r--r--`**:\n\n"
        "- **Owner (6 = 4+2)**: Read (`r`) and Write (`w`)\n"
        "- **Group (4)**: Read-only (`r`)\n"
        "- **Others (4)**: Read-only (`r`)\n\n"
        "**Usage:** Standard permission for regular files (e.g. text documents, HTML files, configuration files)."
    ),
    "chmod +x": (
        "**`chmod +x <file>`** adds execute permission for all users (owner, group, others) on the specified file, "
        "allowing it to be executed as a program or script."
    ),
    "df -h": (
        "**`df -h`** (*Disk Free - Human Readable*) displays filesystem disk space usage for all mounted partitions "
        "in human-friendly units (MB, GB, TB) along with mount points and percentages used."
    ),
    "free -m": (
        "**`free -m`** displays the system's total, used, free, shared, buffer/cache, and available RAM and swap space in megabytes."
    ),
    "free -h": (
        "**`free -h`** displays memory and swap usage with automatically chosen human-readable units (MB, GB)."
    ),
    "top": (
        "**`top`** is a real-time terminal monitor that displays dynamic system statistics: CPU load, memory utilization, "
        "and a list of currently running processes ordered by resource consumption."
    ),
    "htop": (
        "**`htop`** is an enhanced, interactive process viewer with color-coded CPU core meters, memory bars, tree views, "
        "and mouse support for scrolling and killing processes."
    ),
    "ps aux": (
        "**`ps aux`** lists every process running on the system:\n"
        "- **`a`**: processes for all users\n"
        "- **`u`**: display process owner and memory/CPU percentages\n"
        "- **`x`**: include processes not attached to a terminal (daemons)"
    ),
    "tar": (
        "**`tar`** (*Tape Archive*) archives multiple files into a single archive file.\n"
        "- Create gzip archive: `tar -czvf archive.tar.gz /path/to/dir`\n"
        "- Extract gzip archive: `tar -xzvf archive.tar.gz`"
    ),
    "grep": (
        "**`grep`** (*Global Regular Expression Print*) searches files or streams for lines matching a pattern or regular expression.\n"
        "- Example: `grep -rn \"search_term\" /path/to/dir` (recursive search with line numbers)."
    ),
    "chown": (
        "**`chown`** (*Change Owner*) changes file or directory ownership.\n"
        "- Syntax: `chown user:group filename`\n"
        "- Recursive: `chown -R user:group /path/to/dir`"
    ),
    "systemctl": (
        "**`systemctl`** is the central tool for inspecting and controlling the systemd system and service manager.\n"
        "- Check status: `systemctl status <service>`\n"
        "- Restart service: `systemctl restart <service>`\n"
        "- View logs: `journalctl -u <service>`"
    ),
    "journalctl": (
        "**`journalctl`** queries and displays logs from the systemd journal.\n"
        "- Follow live logs: `journalctl -f`\n"
        "- Service logs: `journalctl -u <service> -n 50`\n"
        "- Errors only: `journalctl -p err`"
    ),
}


class AgentOrchestrator:
    """
    Orchestrates the entire agentic pipeline:
        classify -> plan -> execute -> format / summarize

    Optimized for sub-second deterministic responses for common operations.
    """

    def __init__(self) -> None:
        self.classifier = intent_classifier
        self.planner = task_planner

    @staticmethod
    def _build_diagnostic_answer(collected_context: list[dict[str, Any]]) -> str:
        """Build a fast diagnostic response without LLM latency."""
        results = {item["tool"]: item["output"] for item in collected_context}
        cpu = results.get("diagnostics.cpu", {})
        memory = results.get("diagnostics.memory", {})
        disk = results.get("diagnostics.disk", {})
        network = results.get("diagnostics.network", {})

        findings: list[str] = []

        # CPU
        load_1m = cpu.get("load_avg_1m")
        physical_cores = cpu.get("core_count_physical")
        usage_pct = cpu.get("usage_percent")
        if usage_pct is not None:
            findings.append(f"**CPU Usage**: {usage_pct:.1f}% total across {cpu.get('core_count_logical', 1)} logical cores.")
        if load_1m is not None and physical_cores:
            if load_1m >= physical_cores:
                findings.append(f"**CPU Load**: High at {load_1m:.2f} (1m avg) on {physical_cores} physical cores.")
            elif load_1m >= physical_cores * 0.7:
                findings.append(f"**CPU Load**: Moderately elevated at {load_1m:.2f} on {physical_cores} physical cores.")
            else:
                findings.append(f"**CPU Load**: Normal at {load_1m:.2f} on {physical_cores} physical cores.")

        # Memory
        memory_percent = memory.get("used_percent")
        if memory_percent is not None:
            total_gb = memory.get("total_mb", 0) / 1024.0
            used_gb = memory.get("used_mb", 0) / 1024.0
            if memory_percent >= 90:
                findings.append(f"**Memory (RAM)**: Critically high — {memory_percent:.1f}% used ({used_gb:.1f} GB / {total_gb:.1f} GB).")
            elif memory_percent >= 80:
                findings.append(f"**Memory (RAM)**: High — {memory_percent:.1f}% used ({used_gb:.1f} GB / {total_gb:.1f} GB).")
            else:
                findings.append(f"**Memory (RAM)**: Normal — {memory_percent:.1f}% used ({used_gb:.1f} GB / {total_gb:.1f} GB).")

        # Swap
        swap_pct = memory.get("swap_percent")
        if swap_pct is not None and swap_pct > 50:
            findings.append(f"**Swap Memory**: Elevated at {swap_pct:.1f}% used.")

        # Disk
        disk_percent = disk.get("used_percent")
        if disk_percent is not None:
            total_gb = disk.get("total_gb", 0)
            free_gb = disk.get("free_gb", 0)
            if disk_percent >= 90:
                findings.append(f"**Disk Storage**: Critically full — {disk_percent:.1f}% used ({free_gb:.1f} GB free of {total_gb:.1f} GB).")
            elif disk_percent >= 80:
                findings.append(f"**Disk Storage**: Getting full — {disk_percent:.1f}% used ({free_gb:.1f} GB free of {total_gb:.1f} GB).")
            else:
                findings.append(f"**Disk Storage**: Healthy — {disk_percent:.1f}% used ({free_gb:.1f} GB free of {total_gb:.1f} GB).")

        # Network
        if network:
            status = "Connected" if network.get("internet_connected") else "Offline / Disconnected"
            ip = network.get("local_ip", "Unknown")
            findings.append(f"**Network**: {status} (Local IP: `{ip}`).")

        answer = "### 🔍 System Diagnostics Report\n\n"
        if findings:
            answer += "\n".join(f"- {finding}" for finding in findings)
        else:
            answer += "- No diagnostic metrics were returned."

        # Recommendations
        recommendations: list[str] = []
        if memory_percent is not None and memory_percent >= 80:
            recommendations.append("Close heavy memory-consuming processes or check with `ps aux --sort=-%mem | head -n 10`.")
        if load_1m is not None and physical_cores and load_1m >= physical_cores * 0.7:
            recommendations.append("Inspect CPU-intensive processes with `top` or `htop`.")
        if disk_percent is not None and disk_percent >= 80:
            recommendations.append("Clean up temporary files or inspect large files in your home directory.")

        if recommendations:
            answer += "\n\n**💡 Recommended Actions:**\n"
            answer += "\n".join(f"- {rec}" for rec in recommendations)

        return answer

    @staticmethod
    def _build_file_search_answer(collected_context: list[dict[str, Any]]) -> str:
        """Build a fast file-search response without an LLM call."""
        results = {item["tool"]: item["output"] for item in collected_context}
        search_result = results.get("file_search.search", {})
        matches = search_result.get("matches", [])
        match_count = search_result.get("match_count", len(matches))
        summary = search_result.get("query_summary", "search")

        if not matches:
            return f"📂 **File Search Results** ({summary}):\n\nNo matching files were found in the specified location."

        answer = f"📂 **File Search Results** — Found **{match_count}** matching file(s) ({summary}):\n\n"
        for index, match in enumerate(matches, start=1):
            path = match.get("path", "Unknown path")
            size_mb = match.get("size_mb")
            modified = match.get("modified_iso")

            if size_mb is not None:
                if size_mb >= 1024:
                    size_str = f"**{size_mb / 1024:.2f} GB**"
                else:
                    size_str = f"**{size_mb:.2f} MB**"
                line = f"{index}. `{path}` — {size_str}"
            else:
                line = f"{index}. `{path}`"

            if modified:
                line += f" *(modified {modified})*"

            answer += line + "\n"

        if search_result.get("truncated"):
            answer += "\n*Note: Search results were capped for safety. Additional matching files exist on disk.*"

        return answer.rstrip()

    @staticmethod
    def _build_service_answer(collected_context: list[dict[str, Any]]) -> str:
        """Build a clean service status or action response."""
        results = {item["tool"]: item["output"] for item in collected_context}
        service_data = (
            results.get("service.status")
            or results.get("service.restart")
            or results.get("service.start")
            or results.get("service.stop")
            or {}
        )

        service_name = service_data.get("service", "unknown")
        action = service_data.get("action", "status")
        success = service_data.get("success", False)
        active = service_data.get("active")
        output = service_data.get("output", "")
        error = service_data.get("error")

        state_badge = "🟢 **ACTIVE (RUNNING)**" if active else "🔴 **INACTIVE / STOPPED**"
        if active is None:
            state_badge = "⚪ **UNKNOWN**"

        if service_data.get("requires_confirmation"):
            return (
                f"⚠️ **User Confirmation Required**\n\n"
                f"**Service:** `{service_name}`\n\n"
                f"**Action:** `{action.upper()}`\n\n"
                f"**Notice:** This action modifies running service state (`MODIFYING`). "
                f"Please confirm if you want to {action} `{service_name}`."
            )

        if action == "status":
            answer = f"### ⚙️ Service Status: `{service_name}`\n\n"
            answer += f"- **State**: {state_badge}\n"
            if output:
                answer += f"- **Details**: `{output}`\n"
            if error:
                answer += f"- **Notice**: {error}\n"
        else:
            status_word = "Successfully" if success else "Failed to"
            answer = f"### ⚙️ Service Action: `{action.upper()}` on `{service_name}`\n\n"
            answer += f"- **Result**: {status_word} executed `{action}` on `{service_name}`.\n"
            answer += f"- **Current State**: {state_badge}\n"
            if output:
                answer += f"- **Output**: `{output}`\n"
            if error:
                answer += f"- **Error Details**: {error}\n"


        return answer

    @staticmethod
    def _build_log_answer(collected_context: list[dict[str, Any]]) -> str:
        """Build a clean log analysis summary."""
        results = {item["tool"]: item["output"] for item in collected_context}
        log_data = results.get("logs.journalctl") or results.get("logs.dmesg") or {}

        source = log_data.get("source", "system logs")
        summary = log_data.get("query_summary", "")
        entry_count = log_data.get("entry_count", 0)
        entries = log_data.get("entries", [])

        if not entries:
            return f"📜 **Log Analysis** ({source}):\n\nNo recent log entries matching the filter were found."

        answer = f"📜 **Log Analysis** — Found **{entry_count}** log entries from `{source}` ({summary}):\n\n```text\n"
        # Take the most recent entries up to 20 for clean readable display
        display_entries = entries[-20:] if len(entries) > 20 else entries
        answer += "\n".join(display_entries)
        answer += "\n```"

        if log_data.get("truncated") or len(entries) > 20:
            answer += f"\n*(Showing latest {len(display_entries)} of {entry_count} entries)*"

        return answer

    @staticmethod
    def _build_command_answer(collected_context: list[dict[str, Any]]) -> str:
        """Build a structured command execution response."""
        results = {item["tool"]: item["output"] for item in collected_context}
        cmd_data = results.get("command.execute", {})

        cmd = cmd_data.get("command", "")
        executed = cmd_data.get("executed", False)
        requires_conf = cmd_data.get("requires_confirmation", False)
        stdout = cmd_data.get("stdout", "")
        stderr = cmd_data.get("stderr", "")
        error = cmd_data.get("error")
        validation = cmd_data.get("validation", {})
        verdict = validation.get("verdict", "")

        if verdict == "BLOCKED":
            reason = validation.get("reason", "Command blocked by security policy.")
            return (
                f"🚫 **Command Blocked by Safety Layer**\n\n"
                f"**Command:** `{cmd}`\n\n"
                f"**Security Verdict:** `BLOCKED`\n\n"
                f"**Reason:** {reason}"
            )

        if requires_conf and not executed:
            return (
                f"⚠️ **User Confirmation Required**\n\n"
                f"**Command:** `{cmd}`\n\n"
                f"**Notice:** This command modifies system state (`{validation.get('category', 'MODIFYING')}`). "
                f"Please confirm if you want to execute this command."
            )

        if executed:
            out_text = stdout.strip() or stderr.strip() or "(Command executed with no output)"
            return (
                f"✅ **Command Executed Successfully**\n\n"
                f"**Command:** `{cmd}`\n\n"
                f"```bash\n{out_text}\n```"
            )

        return (
            f"ℹ️ **Command Execution Result**\n\n"
            f"**Command:** `{cmd}`\n\n"
            f"**Details:** {error or 'Execution not completed.'}"
        )

    def _build_learning_answer(self, query: str, concept: Optional[str]) -> Optional[str]:
        """Checks built-in dictionary for instant answers to common Linux queries."""
        target = (concept or query).strip().lower()
        # Direct match
        if target in _LEARNING_KNOWLEDGE:
            return _LEARNING_KNOWLEDGE[target]
        # Partial match
        for key, text in _LEARNING_KNOWLEDGE.items():
            if key in target or target in key:
                return text
        return None

    async def run(self, query: str, confirmed: bool = False) -> AgentRunResult:
        start = time.monotonic()
        timings = AgentTimings()

        # =========================================================
        # 1. CLASSIFICATION
        # =========================================================
        c_start = time.monotonic()
        classification: ClassificationResult = await self.classifier.classify(query)
        timings.classification_ms = int((time.monotonic() - c_start) * 1000)

        logger.info(
            "Classified '%s' as %s (confidence=%.2f) in %sms",
            query,
            classification.intent.value,
            classification.confidence,
            timings.classification_ms,
        )

        # =========================================================
        # 2. PLANNING
        # =========================================================
        p_start = time.monotonic()
        plan: Plan = await self.planner.plan(
            query,
            intent=classification.intent,
            classification=classification,
        )
        timings.planning_ms = int((time.monotonic() - p_start) * 1000)

        logger.info(
            "Plan for '%s' (%sms): %s",
            query,
            timings.planning_ms,
            [step.tool for step in plan.steps],
        )

        # =========================================================
        # 3. EXECUTE TOOLS
        # =========================================================
        t_start = time.monotonic()
        step_results: list[StepExecution] = []
        collected_context: list[dict[str, Any]] = []

        for step in plan.steps:
            if step.tool in {"llm.summarize", "response.formatter"}:
                continue

            step_start = time.monotonic()
            args = self._merge_args(step, classification, confirmed=confirmed)

            if step.tool in {"service.restart", "service.start", "service.stop"} and not confirmed:
                output = {
                    "service": args.get("service_name", ""),
                    "action": step.tool.split(".")[1],
                    "success": False,
                    "requires_confirmation": True,
                    "error": f"Confirmation required to {step.tool.split('.')[1]} service '{args.get('service_name', '')}'",
                }
            else:
                logger.info("Executing step %s: %s args=%s", step.step, step.tool, args)
                output = run_tool(step.tool, args)

            duration_ms = int((time.monotonic() - step_start) * 1000)

            execution = StepExecution(
                step=step.step,
                tool=step.tool,
                description=step.description,
                output=output,
                duration_ms=duration_ms,
            )
            step_results.append(execution)
            collected_context.append({
                "step": step.step,
                "tool": step.tool,
                "description": step.description,
                "output": output,
            })

        timings.tool_execution_ms = int((time.monotonic() - t_start) * 1000)

        # =========================================================
        # 4. FINAL RESPONSE / SYNTHESIS
        # =========================================================
        s_start = time.monotonic()
        intent = classification.intent.value

        if intent == "DIAGNOSTICS":
            final_answer = self._build_diagnostic_answer(collected_context)
        elif intent == "FILE_SEARCH":
            final_answer = self._build_file_search_answer(collected_context)
        elif intent == "SERVICE_MANAGEMENT":
            final_answer = self._build_service_answer(collected_context)
        elif intent == "LOG_ANALYSIS":
            final_answer = self._build_log_answer(collected_context)
        elif intent == "COMMAND_EXECUTION":
            final_answer = self._build_command_answer(collected_context)
        elif intent == "LEARNING_MODE":
            concept = classification.parameters.command_or_concept
            instant_answer = self._build_learning_answer(query, concept)
            if instant_answer:
                final_answer = instant_answer
            else:
                final_answer = await summarize(query, collected_context)
        else:
            final_answer = await summarize(query, collected_context)

        timings.summarization_ms = int((time.monotonic() - s_start) * 1000)
        timings.total_ms = int((time.monotonic() - start) * 1000)

        return AgentRunResult(
            query=query,
            intent=intent,
            confidence=classification.confidence,
            plan=plan.steps,
            step_results=step_results,
            final_answer=final_answer,
            total_duration_ms=timings.total_ms,
            timings=timings,
        )

    @staticmethod
    def _merge_args(
        step: PlanStep,
        classification: ClassificationResult,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Merge planner arguments with parameters extracted by the intent classifier."""
        merged: dict[str, Any] = {}
        params = classification.parameters.model_dump(exclude_none=True)

        if step.tool.startswith("service."):
            if "service_name" in params:
                merged["service_name"] = params["service_name"]

        elif step.tool == "file_search.search":
            merged["search_path"] = params.get("search_path", os.path.expanduser("~"))
            if "file_type" in params:
                merged["file_type"] = params["file_type"]
            if "file_name" in params:
                merged["name_pattern"] = params["file_name"]
            if "min_size_mb" in params:
                merged["min_size_mb"] = params["min_size_mb"]

        elif step.tool.startswith("logs."):
            if "log_filter" in params:
                merged["keyword"] = params["log_filter"]
            if "time_range" in params:
                merged["since"] = params["time_range"]

        elif step.tool == "command.execute":
            if "raw_command" in params:
                merged["command"] = params["raw_command"]
            merged["confirmed"] = confirmed

        elif step.tool == "diagnostics.disk":
            if "search_path" in params:
                merged["scan_path"] = params["search_path"]

        # Planner-specific arguments take precedence
        merged.update(step.args)
        return merged


orchestrator = AgentOrchestrator()