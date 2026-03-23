# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest
from sandbox_agent_runtime.memory.backend_config import ResolvedQmdConfig
from sandbox_agent_runtime.memory.qmd_manager import QmdMemoryManager
from sandbox_agent_runtime.memory.search_manager import close_all_memory_search_managers, get_memory_search_manager


@pytest.fixture(autouse=True)
def _close_memory_managers() -> None:
    close_all_memory_search_managers()


def test_memory_manager_builtin_store_and_retrieve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MEMORY_BACKEND", "builtin")

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    manager = get_memory_search_manager(workspace_dir=workspace_dir, workspace_id="workspace-1")
    manager.upsert_file(
        rel_path="workspace/workspace-1/preferences.md",
        content="User prefers concise weekly summaries.",
        append=False,
    )
    manager.upsert_file(
        rel_path="preference/voice.md",
        content="Use a concise and direct writing style.",
        append=False,
    )

    read = manager.read_file(rel_path="workspace/workspace-1/preferences.md")
    assert "concise weekly summaries" in read.text

    results = manager.search("weekly summaries")
    assert results
    assert results[0].path == "workspace/workspace-1/preferences.md"

    preference_results = manager.search("direct writing style")
    assert preference_results
    assert preference_results[0].path == "preference/voice.md"

    status = manager.status()
    assert status.backend == "builtin"
    assert status.provider == "filesystem"


def test_memory_manager_defaults_to_qmd_and_falls_back_to_builtin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)
    monkeypatch.setenv("MEMORY_QMD_COMMAND", "qmd-not-installed")

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    memory_dir = tmp_path / "memory" / "workspace" / "workspace-2"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "state.md").write_text("Workspace memory baseline.", encoding="utf-8")

    manager = get_memory_search_manager(workspace_dir=workspace_dir, workspace_id="workspace-2")
    status = manager.status()

    assert status.backend == "builtin"
    assert status.requested_provider == "qmd"
    assert status.fallback is not None
    assert status.fallback.get("from") == "qmd"

    results = manager.search("baseline")
    assert results
    assert results[0].path == "workspace/workspace-2/state.md"


def test_qmd_manager_normalizes_qmd_uri_result_path(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    manager = QmdMemoryManager(
        workspace_dir=workspace_dir,
        qmd=ResolvedQmdConfig(
            command="qmd",
            index_name="holaboss-workspace-1",
            search_mode="search",
            workspace_id="workspace-1",
            memory_root_dir=str(tmp_path / "memory"),
            max_results=6,
            max_snippet_chars=700,
            timeout_ms=4000,
            collections=(),
        ),
    )

    resolved = manager._resolve_result_path({"file": "qmd://memory-root/workspace/workspace-1/engagement.md"})
    assert resolved == "workspace/workspace-1/engagement.md"
