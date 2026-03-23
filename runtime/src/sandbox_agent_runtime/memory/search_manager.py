from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from sandbox_agent_runtime.memory.backend_config import resolve_memory_backend_config
from sandbox_agent_runtime.memory.manager_runtime import close_all_builtin_memory_managers, get_builtin_memory_manager
from sandbox_agent_runtime.memory.qmd_manager import QmdMemoryManager
from sandbox_agent_runtime.memory.types import (
    MemoryProviderStatus,
    MemoryReadResult,
    MemorySearchManager,
    MemorySearchOptions,
    MemorySearchResult,
    MemorySyncOptions,
)

_MANAGER_CACHE: dict[str, MemorySearchManager] = {}


class FallbackMemoryManager:
    def __init__(self, *, primary: MemorySearchManager, fallback: MemorySearchManager) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_failed = False
        self._last_error: str | None = None

    def search(self, query: str, opts: MemorySearchOptions | None = None) -> list[MemorySearchResult]:
        if not self._primary_failed:
            try:
                return self._primary.search(query, opts)
            except Exception as exc:
                self._primary_failed = True
                self._last_error = str(exc)
        return self._fallback.search(query, opts)

    def read_file(
        self,
        *,
        rel_path: str,
        from_line: int | None = None,
        lines: int | None = None,
    ) -> MemoryReadResult:
        if not self._primary_failed:
            try:
                return self._primary.read_file(rel_path=rel_path, from_line=from_line, lines=lines)
            except Exception as exc:
                self._primary_failed = True
                self._last_error = str(exc)
        return self._fallback.read_file(rel_path=rel_path, from_line=from_line, lines=lines)

    def upsert_file(self, *, rel_path: str, content: str, append: bool = False) -> MemoryReadResult:
        if not self._primary_failed:
            try:
                return self._primary.upsert_file(rel_path=rel_path, content=content, append=append)
            except Exception as exc:
                self._primary_failed = True
                self._last_error = str(exc)
        return self._fallback.upsert_file(rel_path=rel_path, content=content, append=append)

    def status(self) -> MemoryProviderStatus:
        if not self._primary_failed:
            return self._primary.status()
        fallback_status = self._fallback.status()
        fallback_info = {
            "from": "qmd",
            "reason": self._last_error or "unknown",
        }
        custom = dict(fallback_status.custom)
        custom["fallback"] = fallback_info
        return replace(fallback_status, fallback=fallback_info, custom=custom)

    def sync(self, opts: MemorySyncOptions | None = None) -> None:
        if not self._primary_failed:
            try:
                self._primary.sync(opts)
            except Exception as exc:
                self._primary_failed = True
                self._last_error = str(exc)
            else:
                return
        self._fallback.sync(opts)

    def close(self) -> None:
        self._primary.close()
        self._fallback.close()


def get_memory_search_manager(*, workspace_dir: Path, workspace_id: str) -> MemorySearchManager:
    resolved = resolve_memory_backend_config(workspace_dir=workspace_dir, workspace_id=workspace_id)
    cache_key = _build_cache_key(workspace_dir=workspace_dir, workspace_id=workspace_id, resolved=resolved)
    cached = _MANAGER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if resolved.backend == "qmd" and resolved.qmd is not None:
        try:
            qmd_manager = QmdMemoryManager.create(workspace_dir=workspace_dir, qmd=resolved.qmd)
            manager = FallbackMemoryManager(
                primary=qmd_manager,
                fallback=get_builtin_memory_manager(
                    workspace_dir=workspace_dir,
                    workspace_id=workspace_id,
                    requested_provider="qmd",
                ),
            )
        except Exception as exc:
            manager = get_builtin_memory_manager(
                workspace_dir=workspace_dir,
                workspace_id=workspace_id,
                requested_provider="qmd",
                fallback_reason=str(exc),
            )
        _MANAGER_CACHE[cache_key] = manager
        return manager

    manager = get_builtin_memory_manager(workspace_dir=workspace_dir, workspace_id=workspace_id)
    _MANAGER_CACHE[cache_key] = manager
    return manager


def close_all_memory_search_managers() -> None:
    managers = list(_MANAGER_CACHE.values())
    _MANAGER_CACHE.clear()
    for manager in managers:
        manager.close()
    close_all_builtin_memory_managers()


def _build_cache_key(*, workspace_dir: Path, workspace_id: str, resolved: object) -> str:
    return ":".join([
        str(workspace_dir.resolve()),
        workspace_id,
        json.dumps(resolved, default=_json_default, sort_keys=True),
    ])


def _json_default(value: object) -> object:
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)
