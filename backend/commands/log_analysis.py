"""
log_analysis.py
----------------
Safe, read-only interfaces to journalctl and dmesg. All parameters are
validated against a strict allow-list/regex before being placed into a
subprocess argument list (never a shell string), so there is no path
for shell metacharacters to reach a shell.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Optional

from pydantic import BaseModel, field_validator

from backend.utils.config import settings

logger = logging.getLogger("linuxpilot.logs")

# Only allow simple, safe tokens for unit names / keyword filters.
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._@\-]{1,128}$")
_ALLOWED_PRIORITIES = {"emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"}
_ALLOWED_SINCE = re.compile(
    r"^(today|yesterday|"
    r"\d+\s?(second|minute|hour|day|week)s?\s?ago|"
    r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?)$"
)


class LogQueryError(ValueError):
    pass


class LogEntry(BaseModel):
    raw: str


class LogQueryResult(BaseModel):
    source: str
    query_summary: str
    entry_count: int
    entries: list[str]
    truncated: bool


class JournalctlQuery(BaseModel):
    unit: Optional[str] = None
    priority: Optional[str] = None
    since: Optional[str] = None
    keyword: Optional[str] = None
    max_lines: int = 100

    @field_validator("unit", "keyword")
    @classmethod
    def _validate_token(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _SAFE_TOKEN_RE.match(v):
            raise LogQueryError(f"Value '{v}' contains disallowed characters.")
        return v

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v.lower() not in _ALLOWED_PRIORITIES:
            raise LogQueryError(f"Priority must be one of {_ALLOWED_PRIORITIES}")
        return v.lower()

    @field_validator("since")
    @classmethod
    def _validate_since(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _ALLOWED_SINCE.match(v.strip().lower()):
            raise LogQueryError(
                "since must look like 'today', 'yesterday', '2 hours ago', "
                "or an ISO date/time."
            )
        return v.strip()

    @field_validator("max_lines")
    @classmethod
    def _clamp_max_lines(cls, v: int) -> int:
        return max(1, min(v, 1000))


def query_journalctl(query: JournalctlQuery) -> LogQueryResult:
    args = ["journalctl", "--no-pager", "-n", str(query.max_lines)]
    if query.unit:
        args += ["-u", query.unit]
    if query.priority:
        args += ["-p", query.priority]
    if query.since:
        args += ["--since", query.since]

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=settings.COMMAND_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("journalctl call failed: %s", exc)
        raise LogQueryError(f"Failed to run journalctl: {exc}") from exc

    lines = result.stdout.splitlines()
    if query.keyword:
        lines = [ln for ln in lines if query.keyword.lower() in ln.lower()]

    return LogQueryResult(
        source="journalctl",
        query_summary=" ".join(args[1:]),
        entry_count=len(lines),
        entries=lines[-200:],  # cap payload size regardless of max_lines
        truncated=len(lines) > 200,
    )


class DmesgQuery(BaseModel):
    keyword: Optional[str] = None
    level: Optional[str] = None  # e.g. err, warn
    max_lines: int = 100

    @field_validator("keyword")
    @classmethod
    def _validate_keyword(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _SAFE_TOKEN_RE.match(v):
            raise LogQueryError(f"Value '{v}' contains disallowed characters.")
        return v

    @field_validator("level")
    @classmethod
    def _validate_level(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v.lower() not in _ALLOWED_PRIORITIES:
            raise LogQueryError(f"Level must be one of {_ALLOWED_PRIORITIES}")
        return v.lower()

    @field_validator("max_lines")
    @classmethod
    def _clamp_max_lines(cls, v: int) -> int:
        return max(1, min(v, 1000))


def query_dmesg(query: DmesgQuery) -> LogQueryResult:
    args = ["dmesg", "--ctime"]
    if query.level:
        args += ["--level", query.level]

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=settings.COMMAND_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("dmesg call failed: %s", exc)
        raise LogQueryError(f"Failed to run dmesg: {exc}") from exc

    lines = result.stdout.splitlines()
    if query.keyword:
        lines = [ln for ln in lines if query.keyword.lower() in ln.lower()]
    lines = lines[-query.max_lines :]

    return LogQueryResult(
        source="dmesg",
        query_summary=" ".join(args[1:]) or "(all)",
        entry_count=len(lines),
        entries=lines,
        truncated=False,
    )
