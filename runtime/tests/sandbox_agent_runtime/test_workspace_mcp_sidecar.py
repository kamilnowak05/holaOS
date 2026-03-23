# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

from sandbox_agent_runtime import workspace_mcp_sidecar


def test_decode_enabled_tool_ids_defaults_to_empty_set() -> None:
    enabled = workspace_mcp_sidecar._decode_enabled_tool_ids("")
    assert enabled == frozenset()


def test_register_builtin_workspace_tools_is_noop(tmp_path: Path) -> None:
    class _FakeMcp:
        def tool(self, *, name: str):
            del name

            def _decorator(func):
                return func

            return _decorator

    registered = workspace_mcp_sidecar._register_builtin_workspace_tools(
        mcp=_FakeMcp(),
        workspace_dir=tmp_path,
        workspace_id="workspace-1",
        enabled_tool_ids=frozenset({
            "workspace.memory_search",
            "workspace.cronjobs_list",
        }),
    )
    assert registered == 0
