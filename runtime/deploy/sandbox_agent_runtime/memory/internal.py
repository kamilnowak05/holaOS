from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)


def normalize_rel_path(value: str) -> str:
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("path is required")
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ValueError("absolute paths are not allowed")
    if ".." in path.parts:
        raise ValueError("parent path segments are not allowed")
    return path.as_posix()


def resolve_memory_root_dir(*, workspace_dir: Path, environ: Mapping[str, str] | None = None) -> Path:
    env = environ or os.environ
    configured = (env.get("MEMORY_ROOT_DIR") or "").strip()
    base_dir = workspace_dir.resolve().parent
    if not configured:
        return (base_dir / "memory").resolve()

    candidate = Path(configured).expanduser()
    candidate = (base_dir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    return candidate


def workspace_scope_prefix(*, workspace_id: str) -> str:
    token = (workspace_id or "").strip()
    if not token:
        raise ValueError("workspace_id is required")
    normalized = normalize_rel_path(f"workspace/{token}")
    parts = PurePosixPath(normalized).parts
    if len(parts) != 2 or parts[0] != "workspace":
        raise ValueError("workspace_id must be a single path token")
    return f"{normalized}/"


def is_memory_path(value: str, *, workspace_id: str) -> bool:
    rel = normalize_rel_path(value)
    parts = PurePosixPath(rel).parts
    if len(parts) < 2:
        return False
    if parts[0] == "workspace":
        prefix = workspace_scope_prefix(workspace_id=workspace_id)
        return rel.startswith(prefix)
    return True


def read_line_window(text: str, from_line: int | None = None, lines: int | None = None) -> str:
    if from_line is None and lines is None:
        return text
    split = text.splitlines()
    start = 1 if from_line is None else max(1, from_line)
    max_lines = len(split) if lines is None else max(0, lines)
    if max_lines == 0:
        return ""
    selected = split[start - 1 : start - 1 + max_lines]
    return "\n".join(selected)


def tokenize_query(value: str) -> list[str]:
    return [token.lower() for token in _TOKEN_PATTERN.findall(value)]


def score_text(query: str, text: str) -> float:
    query_l = query.strip().lower()
    if not query_l:
        return 0.0
    hay = text.lower()
    score = 0.0
    if query_l in hay:
        score += 1.0
    tokens = tokenize_query(query_l)
    if not tokens:
        return score
    unique = list(dict.fromkeys(tokens))
    hit_count = 0
    for token in unique:
        if token in hay:
            hit_count += 1
    return score + (hit_count / max(1, len(unique)))


def snippet_for_match(text: str, query: str, *, max_chars: int = 700) -> tuple[str, int, int]:
    lines = text.splitlines()
    if not lines:
        return ("", 1, 1)
    query_l = query.lower().strip()
    target_idx = 0
    for index, line in enumerate(lines):
        if query_l and query_l in line.lower():
            target_idx = index
            break
    start_idx = max(0, target_idx - 2)
    end_idx = min(len(lines), target_idx + 3)
    snippet_text = "\n".join(lines[start_idx:end_idx]).strip()
    if len(snippet_text) > max_chars:
        snippet_text = snippet_text[:max_chars].rstrip()
    return (snippet_text, start_idx + 1, max(start_idx + 1, end_idx))
