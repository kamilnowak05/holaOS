from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from sandbox_agent_runtime.memory.internal import resolve_memory_root_dir, workspace_scope_prefix
from sandbox_agent_runtime.memory.types import MemoryBackend, MemoryCitationsMode

_DEFAULT_QMD_MAX_RESULTS = 6
_DEFAULT_QMD_MAX_SNIPPET_CHARS = 700
_DEFAULT_QMD_TIMEOUT_MS = 4000


@dataclass(frozen=True)
class ResolvedQmdCollection:
    name: str
    path: str


@dataclass(frozen=True)
class ResolvedQmdConfig:
    command: str
    index_name: str
    search_mode: str
    workspace_id: str
    memory_root_dir: str
    max_results: int
    max_snippet_chars: int
    timeout_ms: int
    collections: tuple[ResolvedQmdCollection, ...]


@dataclass(frozen=True)
class ResolvedMemoryBackendConfig:
    backend: MemoryBackend
    citations: MemoryCitationsMode
    qmd: ResolvedQmdConfig | None


def resolve_memory_backend_config(
    *,
    workspace_dir: Path,
    workspace_id: str,
    environ: Mapping[str, str] | None = None,
) -> ResolvedMemoryBackendConfig:
    env = environ or os.environ

    requested_backend = (env.get("MEMORY_BACKEND") or "qmd").strip().lower()
    backend: MemoryBackend = "qmd" if requested_backend == "qmd" else "builtin"

    requested_citations = (env.get("MEMORY_CITATIONS") or "auto").strip().lower()
    citations: MemoryCitationsMode = requested_citations if requested_citations in {"on", "off", "auto"} else "auto"

    if backend != "qmd":
        return ResolvedMemoryBackendConfig(backend="builtin", citations=citations, qmd=None)

    search_mode = (env.get("MEMORY_QMD_SEARCH_MODE") or "search").strip().lower()
    if search_mode not in {"search", "vsearch", "query"}:
        search_mode = "search"

    command = (env.get("MEMORY_QMD_COMMAND") or "qmd").strip() or "qmd"
    index_name = (env.get("MEMORY_QMD_INDEX") or _default_index_name(workspace_id=workspace_id)).strip()
    workspace_scope = workspace_scope_prefix(workspace_id=workspace_id).rstrip("/")
    normalized_workspace_id = workspace_scope.split("/", 2)[1]
    memory_root_dir = resolve_memory_root_dir(workspace_dir=workspace_dir, environ=env)
    max_results = _int_env(env, "MEMORY_QMD_MAX_RESULTS", _DEFAULT_QMD_MAX_RESULTS, minimum=1)
    max_snippet_chars = _int_env(
        env,
        "MEMORY_QMD_MAX_SNIPPET_CHARS",
        _DEFAULT_QMD_MAX_SNIPPET_CHARS,
        minimum=100,
    )
    timeout_ms = _int_env(env, "MEMORY_QMD_TIMEOUT_MS", _DEFAULT_QMD_TIMEOUT_MS, minimum=250)

    include_default = _bool_env(env, "MEMORY_QMD_INCLUDE_DEFAULT_MEMORY", True)
    collections: list[ResolvedQmdCollection] = []
    if include_default:
        collections.append(
            ResolvedQmdCollection(
                name="workspace-memory",
                path=str(memory_root_dir / workspace_scope),
            )
        )
        collections.append(ResolvedQmdCollection(name="memory-root", path=str(memory_root_dir)))

    qmd = ResolvedQmdConfig(
        command=command,
        index_name=index_name,
        search_mode=search_mode,
        workspace_id=normalized_workspace_id,
        memory_root_dir=str(memory_root_dir),
        max_results=max_results,
        max_snippet_chars=max_snippet_chars,
        timeout_ms=timeout_ms,
        collections=tuple(collections),
    )
    return ResolvedMemoryBackendConfig(backend="qmd", citations=citations, qmd=qmd)


def _default_index_name(*, workspace_id: str) -> str:
    base = workspace_id.strip() or "workspace"
    lowered = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-")
    if not lowered:
        lowered = "workspace"
    return f"holaboss-{lowered}"


def _int_env(env: Mapping[str, str], key: str, default: int, *, minimum: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return default
    return parsed


def _bool_env(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}
