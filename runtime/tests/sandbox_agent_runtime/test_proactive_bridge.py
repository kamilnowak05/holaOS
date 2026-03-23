# ruff: noqa: S101

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sandbox_agent_runtime.memory.operations as memory_operations
import sandbox_agent_runtime.runtime_local_state as runtime_local_state
from sandbox_agent_runtime.proactive_bridge import (
    HttpPollingLocalBridgeReceiver,
    LocalRuntimeProactiveBridgeExecutor,
    ProactiveBridgeJob,
    ProactiveBridgeJobType,
    TaskProposalCreateJobPayload,
    WorkspaceMemoryGetJobPayload,
    WorkspaceMemorySearchJobPayload,
    WorkspaceMemoryStatusJobPayload,
    WorkspaceMemorySyncJobPayload,
    WorkspaceMemoryUpsertJobPayload,
)
from sandbox_agent_runtime.runtime_local_state import create_workspace, get_task_proposal


def _write_runtime_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "runtime": {
                "sandbox_id": "desktop:test-sandbox",
                "mode": "product",
                "default_provider": "holaboss_model_proxy",
            },
            "providers": {
                "holaboss_model_proxy": {
                    "kind": "openai_compatible",
                    "api_key": "token-1",
                    "base_url": "http://127.0.0.1:3060/api/v1/model-proxy",
                }
            },
            "integrations": {
                "holaboss": {
                    "enabled": True,
                    "auth_token": "token-1",
                    "user_id": "user-1",
                    "sandbox_id": "desktop:test-sandbox",
                }
            },
        }),
        encoding="utf-8",
    )


def test_http_receiver_uses_runtime_binding_headers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "state" / "runtime-config.json"
    _write_runtime_config(config_path)
    monkeypatch.setenv("HB_SANDBOX_ROOT", str(tmp_path))
    monkeypatch.setenv("HOLABOSS_RUNTIME_CONFIG_PATH", str(config_path))

    receiver = HttpPollingLocalBridgeReceiver(base_url="http://127.0.0.1:3032")

    assert receiver._headers() == {
        "X-API-Key": "token-1",
        "X-Holaboss-User-Id": "user-1",
        "X-Holaboss-Sandbox-Id": "desktop:test-sandbox",
    }


@pytest.mark.asyncio
async def test_local_bridge_executor_creates_task_proposal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sandbox_root = tmp_path / "sandbox"
    config_path = sandbox_root / "state" / "runtime-config.json"
    db_path = sandbox_root / "state" / "runtime.db"
    _write_runtime_config(config_path)
    monkeypatch.setenv("HB_SANDBOX_ROOT", str(sandbox_root))
    monkeypatch.setenv("HOLABOSS_RUNTIME_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HOLABOSS_RUNTIME_DB_PATH", str(db_path))
    monkeypatch.setattr(runtime_local_state, "WORKSPACE_ROOT", str(sandbox_root / "workspace"))
    monkeypatch.setattr(memory_operations, "WORKSPACE_ROOT", str(sandbox_root / "workspace"))

    create_workspace(workspace_id="workspace-1", name="Workspace One", harness="agno")

    executor = LocalRuntimeProactiveBridgeExecutor()
    result = await executor.execute(
        ProactiveBridgeJob(
            job_id="job-1",
            job_type=ProactiveBridgeJobType.task_proposal_create,
            workspace_id="workspace-1",
            payload=TaskProposalCreateJobPayload(
                workspace_id="workspace-1",
                task_name="Review workspace",
                task_prompt="Review the current workspace and propose the next best task.",
                task_generation_rationale="Desktop bridge test.",
            ),
        )
    )

    assert result.status.value == "succeeded"
    stored = get_task_proposal("job-1")
    assert stored is not None
    assert stored["workspace_id"] == "workspace-1"
    assert stored["task_name"] == "Review workspace"


@pytest.mark.asyncio
async def test_local_bridge_executor_supports_all_memory_operations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox_root = tmp_path / "sandbox"
    config_path = sandbox_root / "state" / "runtime-config.json"
    db_path = sandbox_root / "state" / "runtime.db"
    _write_runtime_config(config_path)
    monkeypatch.setenv("HB_SANDBOX_ROOT", str(sandbox_root))
    monkeypatch.setenv("HOLABOSS_RUNTIME_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HOLABOSS_RUNTIME_DB_PATH", str(db_path))
    monkeypatch.setattr(runtime_local_state, "WORKSPACE_ROOT", str(sandbox_root / "workspace"))
    monkeypatch.setattr(memory_operations, "WORKSPACE_ROOT", str(sandbox_root / "workspace"))

    create_workspace(workspace_id="workspace-1", name="Workspace One", harness="agno")
    executor = LocalRuntimeProactiveBridgeExecutor()

    upsert_result = await executor.execute(
        ProactiveBridgeJob(
            job_id="job-memory-upsert",
            job_type=ProactiveBridgeJobType.workspace_memory_upsert,
            workspace_id="workspace-1",
            payload=WorkspaceMemoryUpsertJobPayload(
                workspace_id="workspace-1",
                path="workspace/workspace-1/notes.md",
                content="campaign plan\nnext step",
                append=False,
            ),
        )
    )
    search_result = await executor.execute(
        ProactiveBridgeJob(
            job_id="job-memory-search",
            job_type=ProactiveBridgeJobType.workspace_memory_search,
            workspace_id="workspace-1",
            payload=WorkspaceMemorySearchJobPayload(
                workspace_id="workspace-1",
                query="campaign",
                max_results=5,
                min_score=0.0,
            ),
        )
    )
    get_result = await executor.execute(
        ProactiveBridgeJob(
            job_id="job-memory-get",
            job_type=ProactiveBridgeJobType.workspace_memory_get,
            workspace_id="workspace-1",
            payload=WorkspaceMemoryGetJobPayload(
                workspace_id="workspace-1",
                path="workspace/workspace-1/notes.md",
            ),
        )
    )
    status_result = await executor.execute(
        ProactiveBridgeJob(
            job_id="job-memory-status",
            job_type=ProactiveBridgeJobType.workspace_memory_status,
            workspace_id="workspace-1",
            payload=WorkspaceMemoryStatusJobPayload(workspace_id="workspace-1"),
        )
    )
    sync_result = await executor.execute(
        ProactiveBridgeJob(
            job_id="job-memory-sync",
            job_type=ProactiveBridgeJobType.workspace_memory_sync,
            workspace_id="workspace-1",
            payload=WorkspaceMemorySyncJobPayload(
                workspace_id="workspace-1",
                reason="bridge_sync",
                force=True,
            ),
        )
    )

    assert upsert_result.status.value == "succeeded"
    assert upsert_result.output["path"] == "workspace/workspace-1/notes.md"
    assert search_result.status.value == "succeeded"
    assert search_result.output["results"]
    assert get_result.output["text"]
    assert status_result.output["status"]["backend"] in {"builtin", "qmd"}
    assert sync_result.output["sync"]["success"] is True
