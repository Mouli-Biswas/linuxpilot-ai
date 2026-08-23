"""
command_validator.py
---------------------
The Command Validation Layer that every AI-generated shell command must
pass through before it is ever handed to subprocess. This is the single
most important safety boundary in LinuxPilot AI.

Safety Architecture:
1. READ_ONLY (ALLOWED):
   Safe inspection commands (df, free, ps, systemctl status, find, etc.)
   Can be executed automatically.
2. MODIFYING (REQUIRES_CONFIRMATION):
   State-altering actions (systemctl restart, apt install, rm, mv, chmod, etc.)
   Require explicit user confirmation before execution.
3. DANGEROUS (BLOCKED):
   Catastrophic or destructive actions (rm -rf /, mkfs, dd to device, fork bombs,
   curl pipe bash, disk wipes, etc.)
   Strictly blocked with zero exceptions.

Never use shell=True. Always pass a parsed argument list to subprocess.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from backend.utils.config import settings

logger = logging.getLogger("linuxpilot.validator")


class SafetyCategory(str, Enum):
    READ_ONLY = "READ_ONLY"
    MODIFYING = "MODIFYING"
    DANGEROUS = "DANGEROUS"


class ValidationVerdict(str, Enum):
    ALLOWED = "ALLOWED"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    BLOCKED = "BLOCKED"


@dataclass
class ValidationResult:
    verdict: ValidationVerdict
    category: SafetyCategory
    command: str
    reason: str
    requires_confirmation: bool = False
    matched_rule: Optional[str] = None


@dataclass
class ExecutionResult:
    command: str
    validation: ValidationResult
    executed: bool
    requires_confirmation: bool = False
    return_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Catastrophic command patterns — deny outright, no exceptions.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BlockRule:
    name: str
    pattern: re.Pattern
    explanation: str


_BLOCK_RULES: list[BlockRule] = [
    BlockRule(
        name="rm_recursive_root",
        pattern=re.compile(
            r"\brm\b.*\s-[a-z]*r[a-z]*f[a-z]*\s+/?\s*(\s|$)|"
            r"\brm\b.*\s-[a-z]*f[a-z]*r[a-z]*\s+/?\s*(\s|$)|"
            r"\brm\b.*\s-[a-z]*r[a-z]*f[a-z]*\s+/\*"
        ),
        explanation="Recursive forced deletion targeting the root filesystem or wildcard root.",
    ),
    BlockRule(
        name="rm_recursive_dangerous_path",
        pattern=re.compile(
            r"\brm\b.*-[a-z]*r[a-z]*.*\s(/(bin|boot|etc|lib|lib64|proc|sys|usr|var|root|home)\b)"
        ),
        explanation="Recursive deletion targeting a critical system directory.",
    ),
    BlockRule(
        name="mkfs",
        pattern=re.compile(r"\bmkfs(\.\w+)?\b"),
        explanation="Filesystem formatting commands can irreversibly destroy all data on a disk/partition.",
    ),
    BlockRule(
        name="dd_disk_write",
        pattern=re.compile(r"\bdd\b.*\bof=\s*/dev/"),
        explanation="`dd` writing directly to a block device can destroy partitions or disks.",
    ),
    BlockRule(
        name="shutdown_reboot",
        pattern=re.compile(r"\b(shutdown|reboot|poweroff|halt|init\s+0|init\s+6)\b"),
        explanation="Commands that power off or restart the machine are blocked from automated execution.",
    ),
    BlockRule(
        name="chmod_recursive_root",
        pattern=re.compile(r"\bchmod\b.*-[a-z]*r[a-z]*.*\s(777|000)\s+/?\s*(\s|$)"),
        explanation="Recursive permission changes on root/unqualified paths can break the entire system.",
    ),
    BlockRule(
        name="chown_recursive_unqualified",
        pattern=re.compile(r"\bchown\b.*-[a-z]*r[a-z]*.*\s/?\s*(\s|$)"),
        explanation="Recursive ownership changes without a specific safe target path are blocked.",
    ),
    BlockRule(
        name="fork_bomb",
        pattern=re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
        explanation="Classic fork-bomb pattern that exhausts system resources.",
    ),
    BlockRule(
        name="disk_wipe_utils",
        pattern=re.compile(r"\b(wipefs|shred|fdisk|parted|gparted)\b"),
        explanation="Disk partitioning/wiping utilities are blocked from automated execution.",
    ),
    BlockRule(
        name="curl_pipe_shell",
        pattern=re.compile(r"\b(curl|wget)\b.*\|\s*(sudo\s+)?(bash|sh|zsh)\b"),
        explanation="Piping a remote download directly into a shell is a dangerous untrusted execution pattern.",
    ),
    BlockRule(
        name="passwd_root",
        pattern=re.compile(r"\bpasswd\b\s+root\b"),
        explanation="Changing the root password is not permitted via automated execution.",
    ),
    BlockRule(
        name="userdel_groupdel_root",
        pattern=re.compile(r"\b(userdel|groupdel)\b.*\broot\b"),
        explanation="Modifying the root account/group is blocked.",
    ),
    BlockRule(
        name="iptables_flush",
        pattern=re.compile(r"\biptables\b.*-F\b"),
        explanation="Flushing all firewall rules can expose the system; blocked from automated execution.",
    ),
]

# Base commands known to be read-only / harmless inspection
_READ_ONLY_BASE_COMMANDS: set[str] = {
    "df", "du", "free", "uptime", "uname", "whoami", "echo",
    "cat", "ls", "grep", "find", "ps", "top", "htop",
    "which", "whereis", "head", "tail", "wc", "date",
    "hostname", "id", "env", "printenv", "ip", "ifconfig",
    "netstat", "ss", "ping", "traceroute",
}

# Base commands that modify state and require confirmation
_MODIFYING_BASE_COMMANDS: set[str] = {
    "apt", "apt-get", "dnf", "yum", "pacman", "snap", "pip", "pip3",
    "npm", "systemctl", "service", "rm", "mv", "cp", "mkdir",
    "rmdir", "touch", "chmod", "chown", "kill", "pkill", "git",
}

_ALL_ALLOWED_BASE_COMMANDS: set[str] = _READ_ONLY_BASE_COMMANDS | _MODIFYING_BASE_COMMANDS


def _normalize(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip().lower())


def validate_command(command: str) -> ValidationResult:
    """
    Validates a shell command against the 3-tier safety architecture:
    - READ_ONLY (ALLOWED) -> Can run automatically
    - MODIFYING (REQUIRES_CONFIRMATION) -> Needs explicit user confirmation
    - DANGEROUS (BLOCKED) -> Strictly blocked
    """
    stripped = command.strip()
    if not stripped:
        return ValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            category=SafetyCategory.DANGEROUS,
            command=command,
            reason="Empty command.",
            requires_confirmation=False,
        )

    # shlex.split raises on unbalanced quotes -- treat as suspicious/invalid
    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        return ValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            category=SafetyCategory.DANGEROUS,
            command=command,
            reason=f"Could not safely parse command: {exc}",
            requires_confirmation=False,
        )

    if not tokens:
        return ValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            category=SafetyCategory.DANGEROUS,
            command=command,
            reason="Empty command after parsing.",
            requires_confirmation=False,
        )

    normalized = _normalize(stripped)

    # 1) Blocklist check — catastrophic patterns, checked first and always.
    for rule in _BLOCK_RULES:
        if rule.pattern.search(normalized):
            logger.warning("Command blocked by rule '%s': %s", rule.name, command)
            return ValidationResult(
                verdict=ValidationVerdict.BLOCKED,
                category=SafetyCategory.DANGEROUS,
                command=command,
                reason=rule.explanation,
                requires_confirmation=False,
                matched_rule=rule.name,
            )

    # 2) Chained-command check: split on ; && || | and validate every segment.
    segments = re.split(r"&&|\|\||;|\|", stripped)
    if len(segments) > 1:
        has_modifying = False
        for segment in segments:
            seg = segment.strip()
            if not seg:
                continue
            sub_result = validate_command(seg)
            if sub_result.verdict is ValidationVerdict.BLOCKED:
                return ValidationResult(
                    verdict=ValidationVerdict.BLOCKED,
                    category=SafetyCategory.DANGEROUS,
                    command=command,
                    reason=f"Blocked because chained segment '{seg}' is unsafe: {sub_result.reason}",
                    requires_confirmation=False,
                    matched_rule=sub_result.matched_rule,
                )
            if sub_result.category is SafetyCategory.MODIFYING:
                has_modifying = True

        if has_modifying:
            return ValidationResult(
                verdict=ValidationVerdict.REQUIRES_CONFIRMATION,
                category=SafetyCategory.MODIFYING,
                command=command,
                reason="Chained command contains modifying operations and requires user confirmation.",
                requires_confirmation=True,
            )
        return ValidationResult(
            verdict=ValidationVerdict.ALLOWED,
            category=SafetyCategory.READ_ONLY,
            command=command,
            reason="All chained segments passed read-only validation.",
            requires_confirmation=False,
        )

    # 3) Base-command check
    base_command = tokens[0].split("/")[-1].lower()  # strip path prefix e.g. /usr/bin/
    
    # Strip sudo prefix if present to inspect underlying command
    if base_command == "sudo" and len(tokens) > 1:
        base_command = tokens[1].split("/")[-1].lower()
        sub_cmd_index = 1
    else:
        sub_cmd_index = 0

    if base_command not in _ALL_ALLOWED_BASE_COMMANDS:
        return ValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            category=SafetyCategory.DANGEROUS,
            command=command,
            reason=f"'{base_command}' is not in the approved command allow-list for automated execution.",
            requires_confirmation=False,
        )

    # Special handling for systemctl / service commands:
    # 'systemctl status <unit>', 'systemctl is-active <unit>' are READ_ONLY
    # 'systemctl restart/start/stop' are MODIFYING
    if base_command in {"systemctl", "service"}:
        remaining_tokens = [t.lower() for t in tokens[sub_cmd_index + 1:]]
        if any(action in remaining_tokens for action in ["status", "is-active", "is-enabled", "is-failed"]):
            return ValidationResult(
                verdict=ValidationVerdict.ALLOWED,
                category=SafetyCategory.READ_ONLY,
                command=command,
                reason="Read-only service status check approved.",
                requires_confirmation=False,
            )
        return ValidationResult(
            verdict=ValidationVerdict.REQUIRES_CONFIRMATION,
            category=SafetyCategory.MODIFYING,
            command=command,
            reason="Service modification requires explicit user confirmation.",
            requires_confirmation=True,
        )

    # 4) Categorize as READ_ONLY or MODIFYING
    if base_command in _READ_ONLY_BASE_COMMANDS:
        return ValidationResult(
            verdict=ValidationVerdict.ALLOWED,
            category=SafetyCategory.READ_ONLY,
            command=command,
            reason="Read-only inspection command approved for automatic execution.",
            requires_confirmation=False,
        )

    # Modifying commands require confirmation
    return ValidationResult(
        verdict=ValidationVerdict.REQUIRES_CONFIRMATION,
        category=SafetyCategory.MODIFYING,
        command=command,
        reason=f"Command '{base_command}' modifies system state and requires explicit confirmation.",
        requires_confirmation=True,
    )


def execute_validated_command(command: str, confirmed: bool = False) -> ExecutionResult:
    """
    Validates, then runs the command with subprocess (shell=False).
    - If BLOCKED -> does not execute, returns error reason.
    - If REQUIRES_CONFIRMATION and not confirmed -> returns confirmation requirement.
    - If ALLOWED (READ_ONLY) or confirmed -> executes safely.
    """
    validation = validate_command(command)

    if validation.verdict is ValidationVerdict.BLOCKED:
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=False,
            error=f"Command blocked by safety layer: {validation.reason}",
        )

    if validation.category is SafetyCategory.MODIFYING and not confirmed:
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=True,
            error="Command requires explicit user confirmation before execution.",
        )

    # For modifying commands that are confirmed, check master execution switch
    if validation.category is SafetyCategory.MODIFYING and not settings.ALLOW_COMMAND_EXECUTION:
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=False,
            error="Execution disabled: ALLOW_COMMAND_EXECUTION=false in environment configuration (dry-run mode).",
        )

    try:
        tokens = shlex.split(command)
        result = subprocess.run(
            tokens,
            shell=False,  # NEVER shell=True
            capture_output=True,
            text=True,
            timeout=settings.COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=True,
            requires_confirmation=False,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=False,
            error=f"Command timed out after {settings.COMMAND_TIMEOUT_SECONDS}s.",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.exception("Execution failed for validated command")
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=False,
            error=str(exc),
        )
