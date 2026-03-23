# ruff: noqa: S101
from __future__ import annotations

import pytest
from sandbox_agent_runtime.runtime_config import WorkspaceRuntimePlanBuilder


@pytest.mark.asyncio
async def test_compile_without_agents_md_uses_empty_prompt() -> None:
    workspace_yaml = """
template_id: demo
name: Demo
agents:
  - id: workspace.general
    model: gpt-5.2
mcp_registry:
  allowlist:
    tool_ids: []
  servers: {}
"""

    async def _reader(path: str) -> str:
        raise FileNotFoundError(path)

    plan = await WorkspaceRuntimePlanBuilder().compile(
        workspace_id="workspace-1",
        workspace_yaml=workspace_yaml,
        reference_reader=_reader,
    )
    assert plan.general_config.type == "single"
    assert plan.general_config.agent.prompt == ""


@pytest.mark.asyncio
async def test_compile_ignores_prompt_file_and_uses_agents_md() -> None:
    workspace_yaml = """
template_id: demo
name: Demo
agents:
  - id: workspace.general
    model: gpt-5.2
    prompt_file: prompts/general.md
mcp_registry:
  allowlist:
    tool_ids: []
  servers: {}
"""

    async def _reader(path: str) -> str:
        if path == "AGENTS.md":
            return "You are concise."
        raise FileNotFoundError(path)

    plan = await WorkspaceRuntimePlanBuilder().compile(
        workspace_id="workspace-1",
        workspace_yaml=workspace_yaml,
        reference_reader=_reader,
    )
    assert plan.general_config.type == "single"
    assert plan.general_config.agent.prompt == "You are concise."
