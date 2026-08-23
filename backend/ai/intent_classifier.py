"""
intent_classifier.py
---------------------
Classifies a free-text user query into one of the six LinuxPilot AI
intents.

Optimization Strategy:
- Predictable and obvious queries are classified deterministically in microseconds
  without calling Ollama / LLM.
- Structured slot parameters (search_path, min_size_mb, service_name, action, etc.)
  are extracted locally with robust pattern matching.
- Ollama + Qwen 2.5 Instruct is used for genuinely ambiguous or complex queries.
- If Ollama is unavailable or returns an error, graceful fallback is applied.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from backend.ai.ollama_client import OllamaError, ollama_client
from backend.ai.prompts import LINUXPILOT_SYSTEM_PROMPT
from backend.ai.schemas import ClassificationResult, Intent, IntentParameters

logger = logging.getLogger("linuxpilot.intent_classifier")

# Known services for service management
_KNOWN_SERVICES = {
    "docker": "docker",
    "apache": "apache2",
    "apache2": "apache2",
    "nginx": "nginx",
    "ssh": "ssh",
    "sshd": "ssh",
    "mysql": "mysql",
    "postgresql": "postgresql",
    "postgres": "postgresql",
}

# Lightweight keyword fallback used only if the LLM is unreachable or
# returns something unparsable — keeps the API from hard-failing during
# an Ollama outage, at the cost of lower accuracy.
_FALLBACK_KEYWORDS: dict[Intent, list[str]] = {
    Intent.DIAGNOSTICS: ["slow", "cpu", "memory", "ram", "disk space", "load average", "speed", "performance", "health"],
    Intent.FILE_SEARCH: ["find", "search", "locate", "where is my", "where is", "largest file", "large files"],
    Intent.SERVICE_MANAGEMENT: ["restart", "docker", "nginx", "apache", "mysql", "postgres", "ssh", "systemctl"],
    Intent.LOG_ANALYSIS: ["log", "journalctl", "dmesg", "crash", "error in", "system error"],
    Intent.COMMAND_EXECUTION: ["install", "run", "execute", "apt install", "update package", "df -h", "free"],
    Intent.LEARNING_MODE: ["what does", "explain", "how does", "what is", "meaning of"],
}


def _fallback_classify(query: str) -> ClassificationResult:
    lowered = query.lower()
    for intent, keywords in _FALLBACK_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return ClassificationResult(
                intent=intent,
                confidence=0.50,
                parameters=IntentParameters(),
                raw_query=query,
                reasoning="Keyword fallback used because the LLM was unavailable.",
            )
    return ClassificationResult(
        intent=Intent.LEARNING_MODE,
        confidence=0.20,
        parameters=IntentParameters(command_or_concept=query),
        raw_query=query,
        reasoning="No confident match; defaulted to LEARNING_MODE fallback.",
    )


# ---------------------------------------------------------------------------
# DETERMINISTIC MATCHERS & SLOT EXTRACTORS
# ---------------------------------------------------------------------------

def _match_diagnostics(query: str, lowered: str) -> Optional[ClassificationResult]:
    diagnostic_phrases = [
        "running slowly", "computer slow", "system slow", "why is my computer slow",
        "why is my computer running slowly", "why is my system slow", "why is system slow",
        "cpu usage", "memory usage", "ram usage", "disk usage", "disk space",
        "system performance", "system health", "check health", "system diagnostics",
        "check cpu", "check memory", "check ram", "check disk", "check network",
        "load average", "high load", "system load", "swap usage", "high memory", "high cpu",
        "how much disk space", "how much ram", "how much memory", "network metrics", "network status",
    ]

    if not any(phrase in lowered for phrase in diagnostic_phrases):
        # Check single keywords only if unambiguous
        if lowered in {"slow", "diagnostics", "check system", "system status", "system load", "network status"}:
            pass
        elif "slow" in lowered and ("computer" in lowered or "system" in lowered or "running" in lowered or "machine" in lowered):
            pass
        else:
            return None


    # Determine resource slot
    resource = "overall"
    if any(k in lowered for k in ["cpu", "processor", "load", "load average"]):
        resource = "cpu"
    elif any(k in lowered for k in ["memory", "ram", "swap"]):
        resource = "memory"
    elif any(k in lowered for k in ["disk", "storage", "space", "partition", "drive"]):
        resource = "disk"
    elif any(k in lowered for k in ["network", "internet", "bandwidth", "ip"]):
        resource = "network"

    return ClassificationResult(
        intent=Intent.DIAGNOSTICS,
        confidence=0.95,
        parameters=IntentParameters(resource=resource),
        raw_query=query,
        reasoning=f"Deterministic match for diagnostics query (resource={resource}).",
    )


def _match_file_search(query: str, lowered: str) -> Optional[ClassificationResult]:
    search_starters = [
        "find ", "search ", "locate ", "where is ", "where are ",
        "find all ", "search for ", "list files ", "show files "
    ]
    has_search_starter = any(lowered.startswith(s) or f" {s}" in lowered for s in search_starters)
    has_size_filter = bool(re.search(r"\b(large files|largest files|larger than|bigger than|size >|size >=|\d+\s*(mb|gb|kb))\b", lowered))

    if not (has_search_starter or has_size_filter):
        return None

    # Do not treat learning queries as file searches (e.g. "explain find command")
    if any(lowered.startswith(k) for k in ["explain", "what is", "how does", "what does"]):
        return None

    params = IntentParameters()

    # 1. Search path extraction
    if "home directory" in lowered or "home dir" in lowered or "my home" in lowered or " in home" in lowered:
        params.search_path = "~"
    elif "downloads" in lowered:
        params.search_path = "~/Downloads"
    elif "documents" in lowered:
        params.search_path = "~/Documents"
    elif "desktop" in lowered:
        params.search_path = "~/Desktop"
    elif "root" in lowered and "directory" in lowered:
        params.search_path = "/"
    else:
        path_match = re.search(r"(?:in|under|at)\s+([/~][\w.\-/]*)", query)
        if path_match:
            params.search_path = path_match.group(1).rstrip(".")
        elif has_size_filter or has_search_starter:
            params.search_path = "~"

    # 2. Min size MB extraction
    size_match = re.search(r"(?:larger than|greater than|bigger than|more than|>|>=)\s*(\d+(?:\.\d+)?)\s*(gb|mb|kb|g|m|k)?", lowered)
    if size_match:
        val = float(size_match.group(1))
        unit = (size_match.group(2) or "mb").lower()
        if unit in {"gb", "g"}:
            params.min_size_mb = val * 1024.0
        elif unit in {"kb", "k"}:
            params.min_size_mb = round(val / 1024.0, 3)
        else:
            params.min_size_mb = val
    elif "large files" in lowered or "largest files" in lowered or "biggest files" in lowered:
        params.min_size_mb = 100.0

    # 3. File type / pattern extraction
    if "python" in lowered or "*.py" in lowered or ".py " in lowered or lowered.endswith(".py"):
        params.file_type = "python"
    elif "pdf" in lowered or "*.pdf" in lowered or ".pdf" in lowered:
        params.file_type = "pdf"
    elif any(k in lowered for k in ["image", "images", "photos", "pictures", "*.png", "*.jpg"]):
        params.file_type = "image"
    elif any(k in lowered for k in ["video", "videos", "movies", "*.mp4", "*.mkv"]):
        params.file_type = "video"
    elif any(k in lowered for k in ["audio", "music", "*.mp3", "*.flac"]):
        params.file_type = "audio"
    elif any(k in lowered for k in ["archive", "tar", "zip", "*.tar.gz", "*.zip"]):
        params.file_type = "archive"
    elif any(k in lowered for k in ["document", "documents", "*.docx", "*.txt"]):
        params.file_type = "document"

    # 4. Explicit file name pattern (e.g. `resume.pdf` or `*.log`)
    name_match = re.search(r"(?:named|called|pattern)\s+['\"]?([\w.\-*]+)['\"]?", query)
    if name_match:
        params.file_name = name_match.group(1)
    elif not params.file_type:
        glob_match = re.search(r"\b([\w\-*]+\.[a-zA-Z0-9*]{1,5})\b", query)
        if glob_match and glob_match.group(1) not in {"python.py", "system.slow"}:
            params.file_name = glob_match.group(1)

    return ClassificationResult(
        intent=Intent.FILE_SEARCH,
        confidence=0.95,
        parameters=params,
        raw_query=query,
        reasoning="Deterministic match for file search query.",
    )


def _match_service_management(query: str, lowered: str) -> Optional[ClassificationResult]:
    # Exclude learning queries like "explain systemctl" or "what is nginx"
    if any(lowered.startswith(k) for k in ["explain", "what is", "how does", "what does"]):
        return None

    # Check for service names
    matched_service = None
    for service_alias, canonical_name in _KNOWN_SERVICES.items():
        if re.search(rf"\b{re.escape(service_alias)}\b", lowered):
            matched_service = canonical_name
            break

    if not matched_service:
        return None

    # Check for service actions
    action = None
    if re.search(r"\b(restart|reload)\b", lowered):
        action = "restart"
    elif re.search(r"\b(start|launch|boot up)\b", lowered):
        action = "start"
    elif re.search(r"\b(stop|kill|shutdown)\b", lowered):
        action = "stop"
    elif re.search(r"\b(status|running|state|is\s+\w+\s+running|check\s+\w+)\b", lowered):
        action = "status"

    if not action:
        # If service mentioned with systemctl
        if "systemctl" in lowered:
            action = "status"
        else:
            return None

    return ClassificationResult(
        intent=Intent.SERVICE_MANAGEMENT,
        confidence=0.95,
        parameters=IntentParameters(service_name=matched_service, action=action),
        raw_query=query,
        reasoning=f"Deterministic match for service management (service={matched_service}, action={action}).",
    )


def _match_log_analysis(query: str, lowered: str) -> Optional[ClassificationResult]:
    if any(lowered.startswith(k) for k in ["explain", "what is", "how does", "what does"]):
        return None

    log_triggers = [
        "system errors", "recent errors", "kernel errors", "kernel logs",
        "dmesg", "journalctl", "syslog", "crash logs", "system logs",
        "recent system errors", "show errors", "check logs", "view logs",
        "error logs", "failed services in log"
    ]

    if not any(trigger in lowered for trigger in log_triggers):
        if not (("log" in lowered or "logs" in lowered) and any(k in lowered for k in ["error", "crash", "recent", "kernel", "system"])):
            return None

    # Extract log source
    log_source = "journalctl"
    if "dmesg" in lowered or "kernel" in lowered:
        log_source = "dmesg"

    # Extract filter
    log_filter = None
    if "error" in lowered or "errors" in lowered or "err" in lowered:
        log_filter = "error"
    elif "crash" in lowered or "failed" in lowered:
        log_filter = "failed"
    else:
        for s in _KNOWN_SERVICES:
            if s in lowered:
                log_filter = s
                break

    # Time range
    time_range = None
    if "today" in lowered:
        time_range = "today"
    elif "yesterday" in lowered:
        time_range = "yesterday"
    elif "1 hour" in lowered or "hour ago" in lowered:
        time_range = "1 hour ago"

    return ClassificationResult(
        intent=Intent.LOG_ANALYSIS,
        confidence=0.95,
        parameters=IntentParameters(log_source=log_source, log_filter=log_filter, time_range=time_range),
        raw_query=query,
        reasoning=f"Deterministic match for log analysis (source={log_source}, filter={log_filter}).",
    )


def _match_learning_mode(query: str, lowered: str) -> Optional[ClassificationResult]:
    explain_prefixes = [
        "explain what ", "explain how ", "explain ", "what does ",
        "what is ", "how does ", "meaning of ", "tell me about ",
        "how do i use ", "what is the difference between "
    ]

    matched_prefix = None
    for prefix in explain_prefixes:
        if lowered.startswith(prefix):
            matched_prefix = prefix
            break

    if not matched_prefix:
        return None

    # Extract the concept / command
    concept = query[len(matched_prefix):].strip(" ?.").strip()
    if not concept:
        concept = query.strip()

    # Clean leading "the " if present
    if concept.lower().startswith("the "):
        concept = concept[4:]
    if concept.lower().startswith("command "):
        concept = concept[8:]
    if concept.lower().endswith(" means"):
        concept = concept[:-6].strip()
    elif concept.lower().endswith(" does"):
        concept = concept[:-5].strip()


    return ClassificationResult(
        intent=Intent.LEARNING_MODE,
        confidence=0.95,
        parameters=IntentParameters(command_or_concept=concept),
        raw_query=query,
        reasoning=f"Deterministic match for learning mode (concept='{concept}').",
    )


def _match_command_execution(query: str, lowered: str) -> Optional[ClassificationResult]:
    # Exclude learning queries
    if any(lowered.startswith(k) for k in ["explain", "what is", "how does", "what does", "meaning of"]):
        return None

    cmd = None
    if lowered.startswith("run ") or lowered.startswith("execute "):
        cmd = query[query.index(" ") + 1:].strip()
    elif lowered.startswith("apt install ") or lowered.startswith("apt-get install ") or lowered.startswith("pip install ") or lowered.startswith("install "):
        cmd = query.strip()
    elif lowered.startswith("apt update") or lowered.startswith("apt-get update"):
        cmd = query.strip()

    else:
        tokens = lowered.split()
        if tokens and tokens[0] in {
            "df", "du", "free", "uptime", "uname", "whoami", "top", "htop", "ps", "ls", "cat", "grep",
            "which", "whereis", "rm", "mv", "cp", "mkdir", "rmdir", "touch", "chmod", "chown", "kill",
            "pkill", "dd", "mkfs", "shutdown", "reboot", "poweroff", "init", "systemctl", "service",
            "curl", "wget", "git", "head", "tail", "wc", "ip", "ifconfig", "ping", "sudo", "iptables"
        }:
            cmd = query.strip()

    if not cmd:
        return None

    return ClassificationResult(
        intent=Intent.COMMAND_EXECUTION,
        confidence=0.95,
        parameters=IntentParameters(raw_command=cmd),
        raw_query=query,
        reasoning=f"Deterministic match for command execution (command='{cmd}').",
    )



# ---------------------------------------------------------------------------
# MAIN INTENT CLASSIFIER CLASS
# ---------------------------------------------------------------------------

class IntentClassifier:
    def __init__(self, client=ollama_client) -> None:
        self.client = client

    async def classify(self, query: str) -> ClassificationResult:
        query = query.strip()
        if not query:
            raise ValueError("Query must not be empty")

        lowered = query.lower()

        # -------------------------------------------------------------------
        # 1. Deterministic Fast-Paths (sub-millisecond execution)
        # -------------------------------------------------------------------

        # Check learning mode first (e.g. "Explain what chmod 755 means")
        learning_result = _match_learning_mode(query, lowered)
        if learning_result:
            return learning_result

        # Check service management (e.g. "Show me the status of nginx", "restart docker")
        service_result = _match_service_management(query, lowered)
        if service_result:
            return service_result

        # Check file search (e.g. "Find all large files in my home directory")
        search_result = _match_file_search(query, lowered)
        if search_result:
            return search_result

        # Check diagnostics (e.g. "Why is my computer running slowly?")
        diag_result = _match_diagnostics(query, lowered)
        if diag_result:
            return diag_result

        # Check log analysis (e.g. "Show recent system errors")
        log_result = _match_log_analysis(query, lowered)
        if log_result:
            return log_result

        # Check command execution (e.g. "df -h", "run apt update")
        cmd_result = _match_command_execution(query, lowered)
        if cmd_result:
            return cmd_result

        # -------------------------------------------------------------------
        # 2. Ollama / LLM Fallback Path for ambiguous queries
        # -------------------------------------------------------------------
        try:
            raw = await self.client.generate_json(
                prompt=query,
                system=LINUXPILOT_SYSTEM_PROMPT,
            )
        except (OllamaError, Exception) as exc:
            logger.warning("Ollama unavailable, using keyword fallback: %s", exc)
            return _fallback_classify(query)

        try:
            params = IntentParameters(**raw.get("parameters", {}))
            result = ClassificationResult(
                intent=Intent(raw["intent"]),
                confidence=float(raw.get("confidence", 0.5)),
                parameters=params,
                raw_query=query,
                reasoning=raw.get("reasoning"),
            )
        except (KeyError, ValueError) as exc:
            logger.error("Malformed classification payload %s (%s)", raw, exc)
            return _fallback_classify(query)

        return result


intent_classifier = IntentClassifier()
