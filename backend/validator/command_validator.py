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
   Require explicit action-bound cryptographic authorization before execution.
   A generic boolean confirmation flag can NEVER independently authorize execution.
3. DANGEROUS (BLOCKED):
   Catastrophic or destructive actions (rm -rf /, mkfs, dd to device, fork bombs,
   curl pipe bash, disk wipes, etc.)
   Strictly blocked with zero exceptions.

Execution Invariants:
- Never use shell=True. Always pass a parsed argument list to subprocess.
- Unsupported shell metacharacters (chaining, redirection, command substitution,
  background execution) are rejected upfront to prevent validation-execution divergence.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.security.authorization import (
    AuthorizationPreview,
    auth_manager,
)
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
    authorization_preview: Optional[AuthorizationPreview] = None


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
    authorization: Optional[AuthorizationPreview] = None
    authorization_status: Optional[str] = None


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

# Unsupported shell metacharacters and constructs for single-command execution.
# LinuxPilot AI executes strictly via argument list (shell=False). Chaining, redirection,
# command substitution, and background execution are strictly rejected.
_UNSUPPORTED_SHELL_SYNTAX_PATTERN: re.Pattern = re.compile(
    r"(&&|\|\||[;&|><]|\$\(|\`|[\r\n])"
)


def _normalize(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip().lower())


def validate_command(command: str) -> ValidationResult:
    """
    Validates a shell command against the 3-tier safety architecture:
    - READ_ONLY (ALLOWED) -> Can run automatically
    - MODIFYING (REQUIRES_CONFIRMATION) -> Needs explicit action-bound authorization
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

    # 1) Blocklist check — catastrophic patterns, checked first and always.
    normalized = _normalize(stripped)
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

    # 2) Strict rejection of unsupported shell metacharacters and chaining.
    # Validation and execution MUST interpret the exact same operation.
    if _UNSUPPORTED_SHELL_SYNTAX_PATTERN.search(stripped):
        logger.warning("Command rejected due to unsupported shell syntax: %s", command)
        return ValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            category=SafetyCategory.DANGEROUS,
            command=command,
            reason="Unsupported shell syntax detected. LinuxPilot AI executes commands strictly as parsed argument lists (shell=False) and rejects shell chaining (&&, ||, ;, |), redirection (>, <), command substitution ($(), `), and background execution (&).",
            requires_confirmation=False,
        )

    # 3) Parse command into tokens using shlex
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

    # 4) Sudo check - Reject sudo by default, including when underlying command is read-only
    raw_base = tokens[0].split("/")[-1].lower()
    if raw_base == "sudo":
        return ValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            category=SafetyCategory.DANGEROUS,
            command=command,
            reason="sudo is rejected by default. Automated execution with elevated privileges is not permitted.",
            requires_confirmation=False,
        )

    verdict, category, reason = _categorize_command_and_arguments(tokens, stripped)
    requires_conf = (verdict == ValidationVerdict.REQUIRES_CONFIRMATION)
    return ValidationResult(
        verdict=verdict,
        category=category,
        command=command,
        reason=reason,
        requires_confirmation=requires_conf,
    )


def _categorize_command_and_arguments(
    tokens: list[str], raw_command: str
) -> tuple[ValidationVerdict, SafetyCategory, str]:
    """
    Granular default-deny argument policy per executable.
    Rejects dangerous subcommands, flags, and indirect execution.
    """
    base_command = tokens[0].split("/")[-1].lower()

    if base_command not in _ALL_ALLOWED_BASE_COMMANDS:
        return (
            ValidationVerdict.BLOCKED,
            SafetyCategory.DANGEROUS,
            f"'{base_command}' is not in the approved command allow-list for automated execution.",
        )

    all_args = [t.lower() for t in tokens[1:]]

    # --- SYSTEMCTL ---
    if base_command == "systemctl":
        non_options = [t.lower() for t in tokens[1:] if not t.startswith("-")]
        modifying_verbs = {
            "restart", "start", "stop", "reload", "enable", "disable", "mask", "unmask",
            "edit", "daemon-reload", "kill", "reboot", "poweroff", "halt", "set-property",
        }
        dangerous_verbs = {"reboot", "poweroff", "halt"}
        if any(t in dangerous_verbs for t in all_args):
            return (
                ValidationVerdict.BLOCKED,
                SafetyCategory.DANGEROUS,
                "systemctl poweroff/reboot/halt is blocked from automated execution.",
            )
        if not non_options:
            return (
                ValidationVerdict.ALLOWED,
                SafetyCategory.READ_ONLY,
                "Read-only systemctl unit listing approved.",
            )
        primary_subcmd = non_options[0]
        has_modifying_token = any(token in modifying_verbs for token in all_args)
        if primary_subcmd in {"status", "is-active", "is-enabled", "is-failed"}:
            if has_modifying_token:
                # Misleading arguments: e.g. 'systemctl restart nginx status'
                return (
                    ValidationVerdict.REQUIRES_CONFIRMATION,
                    SafetyCategory.MODIFYING,
                    "Service modification requires explicit action-bound confirmation.",
                )
            return (
                ValidationVerdict.ALLOWED,
                SafetyCategory.READ_ONLY,
                "Read-only service status check approved.",
            )
        elif primary_subcmd in {"restart", "start", "stop", "reload"}:
            return (
                ValidationVerdict.REQUIRES_CONFIRMATION,
                SafetyCategory.MODIFYING,
                f"systemctl {primary_subcmd} modifies service state and requires explicit action-bound confirmation.",
            )
        else:
            return (
                ValidationVerdict.BLOCKED,
                SafetyCategory.DANGEROUS,
                f"Unsupported or unconstrained systemctl subcommand '{primary_subcmd}'.",
            )

    # --- SERVICE ---
    if base_command == "service":
        modifying_verbs = {"restart", "start", "stop", "reload"}
        if any(t in modifying_verbs for t in all_args):
            return (
                ValidationVerdict.REQUIRES_CONFIRMATION,
                SafetyCategory.MODIFYING,
                "Service modification requires explicit action-bound confirmation.",
            )
        if "status" in all_args or "--status-all" in all_args:
            return (
                ValidationVerdict.ALLOWED,
                SafetyCategory.READ_ONLY,
                "Read-only service status check approved.",
            )
        return (
            ValidationVerdict.BLOCKED,
            SafetyCategory.DANGEROUS,
            "Unsupported service action form.",
        )

    # --- ENV / PRINTENV ---
    if base_command == "printenv":
        return (
            ValidationVerdict.ALLOWED,
            SafetyCategory.READ_ONLY,
            "Read-only environment variable inspection approved.",
        )

    if base_command == "env":
        # Check for indirect program execution (e.g. env bash, env python, etc.)
        args = tokens[1:]
        idx = 0
        while idx < len(args):
            arg = args[idx]
            if arg in {"-i", "-0", "--null", "--ignore-environment"}:
                idx += 1
            elif arg in {"-u", "--unset"} and idx + 1 < len(args):
                idx += 2
            elif arg.startswith("-u=") or arg.startswith("--unset="):
                idx += 1
            elif "=" in arg and not arg.startswith("-"):
                idx += 1
            else:
                return (
                    ValidationVerdict.BLOCKED,
                    SafetyCategory.DANGEROUS,
                    f"Indirect command execution via 'env {arg}' is strictly blocked.",
                )
        return (
            ValidationVerdict.ALLOWED,
            SafetyCategory.READ_ONLY,
            "Read-only environment inspection approved.",
        )

    # --- FIND ---
    if base_command == "find":
        dangerous_flags = {
            "-exec", "-execdir", "-ok", "-okdir", "-delete",
            "-fprint", "-fprint0", "-fprintf", "-fls",
        }
        for t in all_args:
            if t in dangerous_flags or t.startswith("-exec") or t.startswith("-ok"):
                return (
                    ValidationVerdict.BLOCKED,
                    SafetyCategory.DANGEROUS,
                    f"find option '{t}' allows command execution or deletion and is strictly blocked.",
                )
        return (
            ValidationVerdict.ALLOWED,
            SafetyCategory.READ_ONLY,
            "Read-only find file search approved.",
        )

    # --- IP ---
    if base_command == "ip":
        modifying_ip = {"add", "del", "delete", "set", "change", "replace", "flush", "save", "restore"}
        if any(t in modifying_ip for t in all_args):
            return (
                ValidationVerdict.REQUIRES_CONFIRMATION,
                SafetyCategory.MODIFYING,
                "Network configuration modification via 'ip' requires explicit authorization.",
            )
        return (
            ValidationVerdict.ALLOWED,
            SafetyCategory.READ_ONLY,
            "Read-only ip inspection approved.",
        )

    # --- GIT ---
    if base_command == "git":
        for t in all_args:
            if t == "--exec-path" or t.startswith("--exec-path="):
                return (
                    ValidationVerdict.BLOCKED,
                    SafetyCategory.DANGEROUS,
                    "git --exec-path is strictly blocked.",
                )
            if t == "-c":
                return (
                    ValidationVerdict.BLOCKED,
                    SafetyCategory.DANGEROUS,
                    "git -c configuration override is strictly blocked.",
                )
            if t == "config":
                return (
                    ValidationVerdict.BLOCKED,
                    SafetyCategory.DANGEROUS,
                    "git config command is blocked from automated execution.",
                )
            if t == "clean" and any(flag in all_args for flag in ["-f", "-force"]):
                return (
                    ValidationVerdict.BLOCKED,
                    SafetyCategory.DANGEROUS,
                    "git clean -f is blocked from automated execution.",
                )

        subcmds = [t for t in all_args if not t.startswith("-")]
        if not subcmds:
            return (
                ValidationVerdict.ALLOWED,
                SafetyCategory.READ_ONLY,
                "Read-only git status approved.",
            )
        git_sub = subcmds[0]
        if git_sub in {"status", "log", "diff", "branch", "show", "tag", "remote"}:
            if any(m in all_args for m in ["-d", "-D", "add", "rm", "remove", "rename", "set-url"]):
                return (
                    ValidationVerdict.REQUIRES_CONFIRMATION,
                    SafetyCategory.MODIFYING,
                    f"git {git_sub} with modifying flags requires confirmation.",
                )
            return (
                ValidationVerdict.ALLOWED,
                SafetyCategory.READ_ONLY,
                f"Read-only git {git_sub} approved.",
            )
        elif git_sub in {"commit", "add", "checkout", "switch", "stash", "fetch", "pull"}:
            return (
                ValidationVerdict.REQUIRES_CONFIRMATION,
                SafetyCategory.MODIFYING,
                f"git {git_sub} modifies repository state and requires confirmation.",
            )
        else:
            return (
                ValidationVerdict.BLOCKED,
                SafetyCategory.DANGEROUS,
                f"git {git_sub} is not permitted for automated execution.",
            )

    # --- PACKAGE MANAGERS ---
    if base_command in {"apt", "apt-get", "dnf", "yum", "pacman", "snap", "pip", "pip3", "npm"}:
        subcmds = [t.lower() for t in tokens[1:] if not t.startswith("-")]
        read_only_pkg_subcmds = {"list", "search", "show", "view", "info", "check", "outdated"}
        if subcmds and subcmds[0] in read_only_pkg_subcmds:
            return (
                ValidationVerdict.ALLOWED,
                SafetyCategory.READ_ONLY,
                f"Read-only {base_command} {subcmds[0]} approved.",
            )
        return (
            ValidationVerdict.REQUIRES_CONFIRMATION,
            SafetyCategory.MODIFYING,
            f"Package management command '{base_command}' modifies system state and requires confirmation.",
        )

    # --- PROCESS CONTROL ---
    if base_command in {"kill", "pkill"}:
        return (
            ValidationVerdict.REQUIRES_CONFIRMATION,
            SafetyCategory.MODIFYING,
            f"Process control command '{base_command}' modifies state and requires confirmation.",
        )

    # --- FILESYSTEM MODIFYING ---
    if base_command in {"rm", "mv", "cp", "mkdir", "rmdir", "touch", "chmod", "chown"}:
        return (
            ValidationVerdict.REQUIRES_CONFIRMATION,
            SafetyCategory.MODIFYING,
            f"Filesystem command '{base_command}' modifies state and requires confirmation.",
        )

    # --- SAFE INSPECTION COMMANDS ---
    if base_command in _READ_ONLY_BASE_COMMANDS:
        return (
            ValidationVerdict.ALLOWED,
            SafetyCategory.READ_ONLY,
            f"Read-only inspection command '{base_command}' approved for automatic execution.",
        )

    return (
        ValidationVerdict.REQUIRES_CONFIRMATION,
        SafetyCategory.MODIFYING,
        f"Command '{base_command}' modifies system state and requires confirmation.",
    )


def execute_validated_command(
    command: str,
    confirmed: bool = False,
    operation_id: Optional[str] = None,
) -> ExecutionResult:
    """
    Validates, then runs the command with subprocess (shell=False).
    - If BLOCKED -> does not execute, returns error reason.
    - If MODIFYING and not authorized via valid operation_id -> returns confirmation requirement
      with an action-bound authorization ticket preview.
    - If ALLOWED (READ_ONLY) or authorized with valid operation_id -> executes safely.

    A generic boolean confirmed=True without a valid operation_id CANNOT authorize
    a modifying command.
    """
    validation = validate_command(command)

    if validation.verdict is ValidationVerdict.BLOCKED:
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=False,
            error=f"Command blocked by safety layer: {validation.reason}",
            authorization_status="BLOCKED",
        )

    # If modifying command, enforce action-bound authorization
    if validation.category is SafetyCategory.MODIFYING:
        target_resource = f"command:{command.strip()}"
        parameters = {"command": command.strip()}
        expected_postconditions = {"return_code": 0}

        # If no operation_id is provided, create a pending authorization ticket and preview
        if not operation_id:
            auth = auth_manager.create_authorization(
                action="command.execute",
                target_resource=target_resource,
                parameters=parameters,
                expected_postconditions=expected_postconditions,
                action_summary=f"Execute modifying command: `{command.strip()}`",
            )
            preview = auth_manager.to_preview(auth)
            validation.authorization_preview = preview
            return ExecutionResult(
                command=command,
                validation=validation,
                executed=False,
                requires_confirmation=True,
                error="Command requires explicit user approval before execution.",
                authorization=preview,
                authorization_status="PENDING",
            )

        # 1. Non-destructively check authorization status (must be APPROVED)
        decision = auth_manager.check_authorization(
            operation_id=operation_id,
            action="command.execute",
            target_resource=target_resource,
            parameters=parameters,
            expected_postconditions=expected_postconditions,
        )

        if not decision.is_authorized:
            return ExecutionResult(
                command=command,
                validation=validation,
                executed=False,
                requires_confirmation=False,
                error=f"Authorization rejected: {decision.reason}",
                authorization_status="REJECTED",
            )

        # 2. Master execution switch check BEFORE consuming ticket
        if not settings.ALLOW_COMMAND_EXECUTION:
            return ExecutionResult(
                command=command,
                validation=validation,
                executed=False,
                requires_confirmation=False,
                error="Execution disabled: ALLOW_COMMAND_EXECUTION=false in environment configuration (dry-run mode).",
                authorization_status="AUTHORIZED_BUT_DISABLED",
            )

        # 3. Atomically consume the authorization ticket
        consume_decision = auth_manager.validate_and_consume(
            operation_id=operation_id,
            action="command.execute",
            target_resource=target_resource,
            parameters=parameters,
            expected_postconditions=expected_postconditions,
        )

        if not consume_decision.is_authorized:
            return ExecutionResult(
                command=command,
                validation=validation,
                executed=False,
                requires_confirmation=False,
                error=f"Authorization consumption failed: {consume_decision.reason}",
                authorization_status="REJECTED",
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
            authorization_status="CONSUMED" if validation.category is SafetyCategory.MODIFYING else None,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=False,
            error=f"Command timed out after {settings.COMMAND_TIMEOUT_SECONDS}s.",
            authorization_status="FAILED",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.exception("Execution failed for validated command")
        return ExecutionResult(
            command=command,
            validation=validation,
            executed=False,
            requires_confirmation=False,
            error=str(exc),
            authorization_status="FAILED",
        )
