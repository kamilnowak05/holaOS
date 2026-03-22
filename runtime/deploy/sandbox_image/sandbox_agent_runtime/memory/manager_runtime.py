from __future__ import annotations

from pathlib import Path

from sandbox_agent_runtime.memory.manager import BuiltinMemoryManager

_BUILTIN_CACHE: dict[str, BuiltinMemoryManager] = {}


def get_builtin_memory_manager(
    *,
    workspace_dir: Path,
    workspace_id: str,
    requested_provider: str | None = None,
    fallback_reason: str | None = None,
) -> BuiltinMemoryManager:
    key = f"{workspace_dir.resolve()}::{workspace_id.strip()}"
    manager = _BUILTIN_CACHE.get(key)
    if manager is not None and requested_provider is None and fallback_reason is None:
        return manager
    manager = BuiltinMemoryManager(
        workspace_dir=workspace_dir,
        workspace_id=workspace_id,
        requested_provider=requested_provider,
        fallback_reason=fallback_reason,
    )
    _BUILTIN_CACHE[key] = manager
    return manager


def close_all_builtin_memory_managers() -> None:
    managers = list(_BUILTIN_CACHE.values())
    _BUILTIN_CACHE.clear()
    for manager in managers:
        manager.close()
