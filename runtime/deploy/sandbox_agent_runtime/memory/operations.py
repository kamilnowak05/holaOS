from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sandbox_agent_runtime.memory.search_manager import get_memory_search_manager
from sandbox_agent_runtime.memory.types import MemorySearchOptions, MemorySyncOptions
from sandbox_agent_runtime.workspace_scope import WORKSPACE_ROOT, sanitize_workspace_id


def workspace_dir_for_workspace_id(workspace_id: str) -> Path:
    workspace_segment = sanitize_workspace_id(workspace_id)
    path = (Path(WORKSPACE_ROOT) / workspace_segment).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_search(
    *,
    workspace_id: str,
    query: str,
    max_results: int = 6,
    min_score: float = 0.0,
) -> dict[str, Any]:
    manager = get_memory_search_manager(
        workspace_dir=workspace_dir_for_workspace_id(workspace_id),
        workspace_id=workspace_id,
    )
    results = manager.search(
        query,
        opts=MemorySearchOptions(max_results=max_results, min_score=min_score),
    )
    return {
        "results": [asdict(item) for item in results],
        "status": asdict(manager.status()),
    }


def memory_get(
    *,
    workspace_id: str,
    path: str,
    from_line: int | None = None,
    lines: int | None = None,
) -> dict[str, Any]:
    manager = get_memory_search_manager(
        workspace_dir=workspace_dir_for_workspace_id(workspace_id),
        workspace_id=workspace_id,
    )
    return asdict(manager.read_file(rel_path=path, from_line=from_line, lines=lines))


def memory_upsert(
    *,
    workspace_id: str,
    path: str,
    content: str,
    append: bool = False,
) -> dict[str, Any]:
    manager = get_memory_search_manager(
        workspace_dir=workspace_dir_for_workspace_id(workspace_id),
        workspace_id=workspace_id,
    )
    return asdict(manager.upsert_file(rel_path=path, content=content, append=append))


def memory_status(*, workspace_id: str) -> dict[str, Any]:
    manager = get_memory_search_manager(
        workspace_dir=workspace_dir_for_workspace_id(workspace_id),
        workspace_id=workspace_id,
    )
    return asdict(manager.status())


def memory_sync(
    *,
    workspace_id: str,
    reason: str = "manual",
    force: bool = False,
) -> dict[str, Any]:
    manager = get_memory_search_manager(
        workspace_dir=workspace_dir_for_workspace_id(workspace_id),
        workspace_id=workspace_id,
    )
    manager.sync(MemorySyncOptions(reason=reason, force=force))
    return {"success": True, "status": asdict(manager.status())}
