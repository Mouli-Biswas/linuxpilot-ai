"""
file_search.py
---------------
High-performance filesystem search used by the FILE_SEARCH intent. Pure
Python (os.scandir / pathlib), no shell invocation at all, so there's no
injection surface here regardless of what free-text the user typed.
"""

from __future__ import annotations

import datetime
import fnmatch
import logging
import os
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("linuxpilot.file_search")

# Common "type" -> extension-set mapping so the AI layer can pass a
# friendly category like "image" or "pdf" instead of raw glob patterns.
_TYPE_EXTENSIONS: dict[str, set[str]] = {
    "pdf": {".pdf"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"},
    "document": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pdf"},
    "spreadsheet": {".xls", ".xlsx", ".csv", ".ods", ".tsv"},
    "archive": {".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz", ".tgz"},
    "python": {".py", ".pyw", ".ipynb"},
    "code": {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs", ".sh", ".bash", ".zsh", ".html", ".css"},
    "screenshot": {".png", ".jpg", ".jpeg"},
    "log": {".log", ".out", ".err"},
}

_IGNORED_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".cache",
    "$recycle.bin", "system volume information", "appdata", "application data",
    "local settings", ".npm", ".cargo", ".rustup", ".docker", ".gemini",
    ".vscode", ".idea", ".gradle", ".nuget", ".local", "anaconda3", "miniconda3",
    "conda", "pkgs", "site-packages", "dist-packages", "proc", "sys", "dev", "run",
}

# Hard safety ceiling regardless of caller-supplied limits
_MAX_RESULTS_CEILING = 500
_DEFAULT_SEARCH_ROOTS = [str(Path.home())]
_DEFAULT_SEARCH_TIMEOUT_SECONDS = 2.5


class FileMatch(BaseModel):
    path: str
    size_mb: float
    modified_iso: str


class FileSearchQuery(BaseModel):
    name_pattern: Optional[str] = Field(None, description="Substring or glob to match against filename")
    file_type: Optional[str] = Field(None, description="Category (e.g. pdf, image, python) or raw extension (e.g. *.py, .pdf)")
    min_size_mb: Optional[float] = Field(None, ge=0)
    max_size_mb: Optional[float] = Field(None, ge=0)
    search_path: Optional[str] = Field(None, description="Root directory to search; defaults to home dir")
    max_results: int = Field(50, ge=1, le=_MAX_RESULTS_CEILING)
    max_depth: int = Field(10, ge=1, le=25, description="Max directory recursion depth")


class FileSearchResult(BaseModel):
    query_summary: str
    match_count: int
    matches: list[FileMatch]
    truncated: bool


def _resolve_extensions(file_type: Optional[str]) -> Optional[set[str]]:
    if not file_type:
        return None
    cleaned = file_type.strip().lower()
    if cleaned in _TYPE_EXTENSIONS:
        return _TYPE_EXTENSIONS[cleaned]
    # If user provided a raw extension pattern like "*.py", ".py", "py"
    ext = cleaned.lstrip("*")
    if not ext.startswith("."):
        ext = f".{ext}"
    return {ext}


def search_files(query: FileSearchQuery) -> FileSearchResult:
    roots = [query.search_path] if query.search_path else _DEFAULT_SEARCH_ROOTS
    extensions = _resolve_extensions(query.file_type)

    matches: list[FileMatch] = []
    start_time = time.monotonic()
    timed_out = False

    for root in roots:
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists():
            logger.warning("Search root does not exist: %s", root_path)
            continue

        walk_matches, to = _scandir_walk(
            str(root_path),
            query=query,
            extensions=extensions,
            start_time=start_time,
            current_depth=0,
        )
        matches.extend(walk_matches)
        if to:
            timed_out = True
            break
        if len(matches) >= query.max_results * 2:
            break

    matches.sort(key=lambda m: m.size_mb, reverse=True)
    truncated = len(matches) > query.max_results or timed_out
    matches = matches[: query.max_results]

    summary_parts = []
    if query.name_pattern:
        summary_parts.append(f"name~'{query.name_pattern}'")
    if query.file_type:
        summary_parts.append(f"type={query.file_type}")
    if query.min_size_mb:
        summary_parts.append(f">= {query.min_size_mb}MB")
    if query.max_size_mb:
        summary_parts.append(f"<= {query.max_size_mb}MB")
    if query.search_path:
        summary_parts.append(f"in '{query.search_path}'")
    summary = ", ".join(summary_parts) or "all files"

    return FileSearchResult(
        query_summary=summary, match_count=len(matches), matches=matches, truncated=truncated
    )


def _scandir_walk(
    dir_path: str,
    query: FileSearchQuery,
    extensions: Optional[set[str]],
    start_time: float,
    current_depth: int,
) -> tuple[list[FileMatch], bool]:
    results: list[FileMatch] = []
    timed_out = False

    if current_depth > query.max_depth:
        return results, False

    # Deadline check
    if time.monotonic() - start_time > _DEFAULT_SEARCH_TIMEOUT_SECONDS:
        return results, True

    try:
        with os.scandir(dir_path) as iterator:
            for entry in iterator:
                # Periodic deadline check
                if time.monotonic() - start_time > _DEFAULT_SEARCH_TIMEOUT_SECONDS:
                    return results, True

                name = entry.name
                name_lower = name.lower()

                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                except (OSError, PermissionError):
                    continue

                if is_directory:
                    # Skip internal/hidden dot directories and heavy caches
                    if name.startswith(".") or name_lower in _IGNORED_DIRS:
                        continue

                    sub_matches, to = _scandir_walk(
                        entry.path,
                        query=query,
                        extensions=extensions,
                        start_time=start_time,
                        current_depth=current_depth + 1,
                    )
                    results.extend(sub_matches)
                    if to:
                        return results, True
                    if len(results) >= query.max_results * 3:
                        return results, False

                else:
                    # Extension / type pre-filter before calling stat
                    if extensions:
                        if not any(name_lower.endswith(ext) for ext in extensions):
                            continue

                    # Name pattern pre-filter
                    if query.name_pattern:
                        pat = query.name_pattern.lower()
                        if not (pat in name_lower or fnmatch.fnmatch(name_lower, pat)):
                            continue

                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except (OSError, PermissionError):
                        continue

                    size_mb = stat.st_size / 1024 / 1024
                    if query.min_size_mb is not None and size_mb < query.min_size_mb:
                        continue
                    if query.max_size_mb is not None and size_mb > query.max_size_mb:
                        continue

                    results.append(
                        FileMatch(
                            path=entry.path,
                            size_mb=round(size_mb, 2),
                            modified_iso=_iso_time(stat.st_mtime),
                        )
                    )
                    if len(results) >= query.max_results * 3:
                        return results, False

    except (OSError, PermissionError):
        pass

    return results, timed_out


def _iso_time(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch).isoformat(timespec="seconds")
