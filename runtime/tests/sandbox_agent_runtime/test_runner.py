# ruff: noqa: S101

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel
from sandbox_agent_runtime import runner as runner_module
from sandbox_agent_runtime.runner import (
    RunnerRequest,
    _anthropic_claude_kwargs,
    _build_opencode_runtime_config,
    _decode_request,
    _execute_request,
    _map_opencode_event,
    _model_proxy_base_root_url,
    _opencode_provider_config_payload,
    _resolve_agno_model_id,
    _resolve_model_client_config,
    _selected_harness,
    _should_emit_opencode_event,
    _workspace_mcp_failure_detail,
    _workspace_mcp_log_path,
)
from sandbox_agent_runtime.runtime_config.models import ResolvedMcpServerConfig, ResolvedMcpToolRef
from sandbox_agent_runtime.runtime_config_adapter import (
    CompiledWorkspaceRuntimePlan,
    WorkspaceGeneralMemberConfig,
    WorkspaceGeneralSingleConfig,
    WorkspaceGeneralTeamConfig,
)

_RUNTIME_EXEC_CONTEXT_KEY = "_sandbox_runtime_exec_v1"
_ORIGINAL_ENSURE_OPENCODE_MCP_SERVERS = runner_module._ensure_opencode_mcp_servers


def _runtime_exec_context(
    *,
    run_id: str = "run-1",
    model_proxy_api_key: str = "hbrt.v1.run-token",
    sandbox_id: str = "sandbox-1",
    model_proxy_base_url: str = "http://sandbox-runtime:3060/api/v1/model-proxy/openai/v1",
    model_proxy_provider: str | None = "openai_compatible",
    harness: str | None = None,
    harness_session_id: str | None = None,
) -> dict[str, dict[str, str]]:
    payload = {
        "run_id": run_id,
        "model_proxy_api_key": model_proxy_api_key,
        "sandbox_id": sandbox_id,
        "model_proxy_base_url": model_proxy_base_url,
    }
    if model_proxy_provider:
        payload["model_proxy_provider"] = model_proxy_provider
    if harness:
        payload["harness"] = harness
    if harness_session_id:
        payload["harness_session_id"] = harness_session_id
    return {
        _RUNTIME_EXEC_CONTEXT_KEY: payload,
    }


@pytest.fixture(autouse=True)
def _clear_harness_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "agno")
    monkeypatch.setenv("HOLABOSS_MODEL_PROXY_BASE_URL", "http://sandbox-runtime:3060/api/v1/model-proxy")


@pytest.fixture(autouse=True)
def _noop_workspace_mcp_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _start_sidecar(*, workspace_dir, compiled_plan, workspace_id, sandbox_id, physical_server_id):
        del workspace_dir, compiled_plan, workspace_id, sandbox_id, physical_server_id
        return None

    async def _stop_sidecar(sidecar):
        del sidecar
        return None

    def _effective_servers(*, compiled_plan, sidecar, server_id_map=None):
        del compiled_plan, sidecar, server_id_map
        return ()

    async def _connect_agno(*, mcp_servers, tool_refs_by_server):
        del mcp_servers, tool_refs_by_server
        return ()

    async def _close_agno(*, mcp_tools):
        del mcp_tools
        return None

    monkeypatch.setattr("sandbox_agent_runtime.runner._start_workspace_mcp_sidecar", _start_sidecar)
    monkeypatch.setattr("sandbox_agent_runtime.runner._stop_workspace_mcp_sidecar", _stop_sidecar)
    monkeypatch.setattr("sandbox_agent_runtime.runner._effective_mcp_server_payloads", _effective_servers)
    monkeypatch.setattr("sandbox_agent_runtime.runner._connect_agno_mcp_tools", _connect_agno)
    monkeypatch.setattr("sandbox_agent_runtime.runner._close_agno_mcp_tools", _close_agno)
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._mcp_tool_refs_by_server",
        lambda compiled_plan, server_id_map=None: {},
    )


@pytest.fixture(autouse=True)
def _workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("sandbox_agent_runtime.runner.WORKSPACE_ROOT", str(workspace_root))


def test_selected_harness_defaults_to_agno_for_oss_flavor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_AGENT_HARNESS", raising=False)
    monkeypatch.setenv("HOLABOSS_RUNTIME_FLAVOR", "oss")

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context={},
    )

    assert _selected_harness(request=request) == "agno"


def test_model_proxy_base_root_url_accepts_product_base_url_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOLABOSS_MODEL_PROXY_BASE_URL", raising=False)
    monkeypatch.setenv("HOLABOSS_MODEL_PROXY_BASE_URL", "https://runtime.example/api/v1/model-proxy")

    assert _model_proxy_base_root_url() == "https://runtime.example/api/v1/model-proxy"


def test_opencode_ready_timeout_seconds_defaults_to_30(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_READY_TIMEOUT_S", raising=False)

    assert runner_module._opencode_ready_timeout_seconds() == 30.0


def test_opencode_ready_timeout_seconds_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCODE_READY_TIMEOUT_S", "45")

    assert runner_module._opencode_ready_timeout_seconds() == 45.0


def test_opencode_base_url_defaults_to_server_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_BASE_URL", raising=False)
    monkeypatch.setenv("OPENCODE_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("OPENCODE_SERVER_PORT", "5096")

    assert runner_module._opencode_base_url() == "http://127.0.0.1:5096"


def test_opencode_base_url_prefers_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCODE_BASE_URL", "http://127.0.0.1:4096/")
    monkeypatch.setenv("OPENCODE_SERVER_PORT", "5096")

    assert runner_module._opencode_base_url() == "http://127.0.0.1:4096"


def test_workspace_mcp_failure_detail_includes_stderr_and_stdout_tails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("sandbox_agent_runtime.runner.WORKSPACE_ROOT", str(workspace_root))

    stderr_path = _workspace_mcp_log_path(physical_server_id="workspace__abc123", stream="stderr")
    stdout_path = _workspace_mcp_log_path(physical_server_id="workspace__abc123", stream="stdout")
    stderr_path.write_text("stderr-line-1\nstderr-line-2\n", encoding="utf-8")
    stdout_path.write_text("stdout-line-1\n", encoding="utf-8")

    detail = _workspace_mcp_failure_detail(physical_server_id="workspace__abc123")

    assert "stderr_tail=stderr-line-1\nstderr-line-2" in detail
    assert "stdout_tail=stdout-line-1" in detail


@pytest.mark.asyncio
async def test_wait_for_opencode_ready_uses_opencode_error_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sandbox_agent_runtime.runner._WORKSPACE_MCP_READY_POLL_S", 0.001)

    class _AlwaysFailClient:
        async def __aenter__(self) -> _AlwaysFailClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> None:
            raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner.httpx.AsyncClient",
        lambda timeout=2.0, trust_env=False: _AlwaysFailClient(),
    )

    with pytest.raises(TimeoutError, match="OpenCode sidecar readiness timed out"):
        await runner_module._wait_for_opencode_ready(
            url="http://127.0.0.1:4096/mcp",
            timeout_seconds=0.01,
        )


@pytest.mark.asyncio
async def test_execute_request_emits_run_failed_without_model_proxy_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return _single_plan()

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context={},
    )

    exit_code = await _execute_request(request)
    assert exit_code == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    assert lines
    event = json.loads(lines[-1])
    assert event["event_type"] == "run_failed"
    assert event["session_id"] == "session-1"
    assert event["input_id"] == "input-1"
    assert "_sandbox_runtime_exec_v1.model_proxy_api_key" in event["payload"]["message"]
    assert "_sandbox_runtime_exec_v1.sandbox_id" in event["payload"]["message"]


@pytest.mark.asyncio
async def test_workspace_mcp_is_ready_disables_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _ReadyClient:
        async def __aenter__(self) -> _ReadyClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> httpx.Response:
            return httpx.Response(406, request=httpx.Request("GET", url))

    def _fake_async_client(*, timeout: float = 2.0, trust_env: bool = True) -> _ReadyClient:
        captured["timeout"] = timeout
        captured["trust_env"] = trust_env
        return _ReadyClient()

    monkeypatch.setattr("sandbox_agent_runtime.runner.httpx.AsyncClient", _fake_async_client)

    ready = await runner_module._workspace_mcp_is_ready(url="http://127.0.0.1:50444/mcp")

    assert ready is True
    assert captured["timeout"] == 2.0
    assert captured["trust_env"] is False


def test_decode_request_round_trip() -> None:
    payload = {
        "workspace_id": "workspace-1",
        "session_id": "session-1",
        "input_id": "input-1",
        "instruction": "hello",
        "context": {"k": "v"},
        "debug": True,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

    request = _decode_request(encoded)

    assert request.holaboss_user_id is None
    assert request.workspace_id == "workspace-1"
    assert request.context == {"k": "v"}
    assert request.debug is True


@pytest.mark.asyncio
async def test_execute_request_emits_run_failed_on_runner_error_chunk(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return _single_plan()

    class _Event:
        def __init__(self, value: str) -> None:
            self.value = value

    class _ErrorChunk:
        event = _Event("TeamRunError")
        content = "insufficient_quota"

    class _FakeRunner:
        async def arun(self, instruction: str, **kwargs):
            del instruction, kwargs
            yield _ErrorChunk()

    def _fake_build_runner_from_plan(*, request, compiled_plan, model_client_config, team_tools, member_tools):
        del request, compiled_plan, model_client_config, team_tools, member_tools
        return _FakeRunner()

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_runner_from_plan",
        _fake_build_runner_from_plan,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )

    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    assert lines
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "run_failed"]
    assert events[-1]["payload"]["event"] == "TeamRunError"
    assert "insufficient_quota" in events[-1]["payload"]["message"]


@pytest.mark.asyncio
async def test_execute_request_emits_output_from_completed_chunk_when_no_deltas(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return _single_plan()

    class _Event:
        def __init__(self, value: str) -> None:
            self.value = value

    class _CompletedChunk:
        event = _Event("TeamRunCompleted")
        content = "Hello from team completion"

    class _FakeRunner:
        async def arun(self, instruction: str, **kwargs):
            del instruction, kwargs
            yield _CompletedChunk()

    def _fake_build_runner_from_plan(*, request, compiled_plan, model_client_config, team_tools, member_tools):
        del request, compiled_plan, model_client_config, team_tools, member_tools
        return _FakeRunner()

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_runner_from_plan",
        _fake_build_runner_from_plan,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )

    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    assert lines
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "output_delta", "run_completed"]
    assert events[2]["payload"]["event"] == "TeamRunCompleted"
    assert events[2]["payload"]["delta"] == "Hello from team completion"


@pytest.mark.asyncio
async def test_execute_request_pushes_events_to_callback_when_push_context_present(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return _single_plan()

    class _Event:
        def __init__(self, value: str) -> None:
            self.value = value

    class _CompletedChunk:
        event = _Event("TeamRunCompleted")
        content = "Hello callback"

    class _FakeRunner:
        async def arun(self, instruction: str, **kwargs):
            del instruction, kwargs
            yield _CompletedChunk()

    def _fake_build_runner_from_plan(*, request, compiled_plan, model_client_config, team_tools, member_tools):
        del request, compiled_plan, model_client_config, team_tools, member_tools
        return _FakeRunner()

    callback_calls: list[dict] = []

    class _FakePushAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def post(self, url: str, *, headers: dict[str, str], json: dict):
            callback_calls.append({"url": url, "headers": headers, "json": json})
            return SimpleNamespace(status_code=200)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_runner_from_plan",
        _fake_build_runner_from_plan,
    )
    monkeypatch.setattr("sandbox_agent_runtime.runner.httpx.AsyncClient", _FakePushAsyncClient)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context={
            **_runtime_exec_context(run_id="run-1", model_proxy_api_key="hbrt.v1.run-1"),
            "_sandbox_runtime_push_v1": {
                "protocol_version": "1.0",
                "run_id": "run-1",
                "callback_url": "http://sandbox-runtime.local/push/events",
                "callback_token": "cb-token",
                "ack_timeout_ms": 1000,
                "max_retries": 1,
            },
        },
    )

    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    assert lines
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "output_delta", "run_completed"]

    assert len(callback_calls) == len(events)
    assert callback_calls[0]["url"] == "http://sandbox-runtime.local/push/events"
    assert callback_calls[0]["headers"]["Authorization"] == "Bearer cb-token"
    assert "X-API-Key" not in callback_calls[0]["headers"]
    assert callback_calls[0]["json"]["run_id"] == "run-1"
    assert callback_calls[-1]["json"]["event_type"] == "run_completed"


def test_resolve_model_client_config_prefers_runtime_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(run_id="run-ctx-1", model_proxy_api_key="hbrt.v1.proxy-user-key"),
    )

    config = _resolve_model_client_config(request=request, model_proxy_provider="openai_compatible")
    assert config.model_proxy_provider == "openai_compatible"
    assert config.base_url == "http://sandbox-runtime:3060/api/v1/model-proxy/openai/v1"
    assert config.api_key == "hbrt.v1.proxy-user-key"
    assert config.default_headers == {
        "X-API-Key": "hbrt.v1.proxy-user-key",
        "X-Holaboss-Sandbox-Id": "sandbox-1",
        "X-Holaboss-Run-Id": "run-ctx-1",
        "X-Holaboss-Session-Id": "session-1",
        "X-Holaboss-Workspace-Id": "workspace-1",
        "X-Holaboss-Input-Id": "input-1",
    }


def test_resolve_model_client_config_uses_direct_openai_fallback_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "direct-openai-key")

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context={},
    )

    config = _resolve_model_client_config(request=request, model_proxy_provider="openai_compatible")
    assert config.model_proxy_provider == "openai_compatible"
    assert config.api_key == "direct-openai-key"
    assert config.base_url is None
    assert config.default_headers is None


def test_resolve_model_client_config_uses_direct_openai_fallback_for_oss_flavor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.setenv("HOLABOSS_RUNTIME_FLAVOR", "oss")
    monkeypatch.setenv("OPENAI_API_KEY", "direct-openai-key")

    request = RunnerRequest(
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context={},
    )

    config = _resolve_model_client_config(request=request, model_proxy_provider="openai_compatible")
    assert config.model_proxy_provider == "openai_compatible"
    assert config.api_key == "direct-openai-key"
    assert config.base_url is None
    assert config.default_headers is None


def test_resolve_model_client_config_supports_anthropic_native_for_opencode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(run_id="run-ctx-1", model_proxy_api_key="hbrt.v1.proxy-user-key"),
    )

    config = _resolve_model_client_config(request=request, model_proxy_provider="anthropic_native", harness="opencode")
    assert config.model_proxy_provider == "anthropic_native"
    assert config.base_url == "http://sandbox-runtime:3060/api/v1/model-proxy/anthropic/v1"
    assert config.default_headers is not None
    assert config.default_headers["X-Holaboss-Sandbox-Id"] == "sandbox-1"
    assert config.default_headers["X-Holaboss-Run-Id"] == "run-ctx-1"


def test_resolve_model_client_config_defaults_to_openai_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(run_id="run-ctx-1", model_proxy_api_key="hbrt.v1.proxy-user-key"),
    )

    config = _resolve_model_client_config(request=request, harness="opencode")
    assert config.model_proxy_provider == "openai_compatible"
    assert config.base_url == "http://sandbox-runtime:3060/api/v1/model-proxy/openai/v1"


def test_resolve_model_client_config_supports_anthropic_native_for_agno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )

    config = _resolve_model_client_config(request=request, model_proxy_provider="anthropic_native", harness="agno")
    assert config.model_proxy_provider == "anthropic_native"
    assert config.base_url == "http://sandbox-runtime:3060/api/v1/model-proxy/anthropic/v1"


def test_resolve_agno_model_id_strips_openai_provider_prefix() -> None:
    config = runner_module._ModelClientConfig(
        model_proxy_provider="openai_compatible",
        api_key="direct-openai-key",
    )
    model_name = "openai/gpt-4o-mini"

    assert _resolve_agno_model_id(model_token=model_name, model_client_config=config) == "gpt-4o-mini"


def test_resolve_agno_model_id_strips_anthropic_provider_prefix() -> None:
    config = runner_module._ModelClientConfig(
        model_proxy_provider="anthropic_native",
        api_key="direct-anthropic-key",
    )
    model_name = "anthropic/claude-3-7-sonnet-20250219"

    assert (
        _resolve_agno_model_id(
            model_token=model_name,
            model_client_config=config,
        )
        == "claude-3-7-sonnet-20250219"
    )


def test_anthropic_claude_kwargs_passes_base_url_and_headers() -> None:
    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(run_id="run-ctx-1", model_proxy_api_key="hbrt.v1.proxy-user-key"),
    )
    model_client_config = _resolve_model_client_config(
        request=request,
        model_proxy_provider="anthropic_native",
        harness="agno",
    )

    kwargs = _anthropic_claude_kwargs(
        model_id="claude-3-5-sonnet-20241022",
        model_client_config=model_client_config,
    )
    assert kwargs["id"] == "claude-3-5-sonnet-20241022"
    assert kwargs["api_key"] == "hbrt.v1.proxy-user-key"
    assert kwargs["client_params"]["base_url"] == "http://sandbox-runtime:3060/api/v1/model-proxy/anthropic/v1"
    assert kwargs["default_headers"]["X-Holaboss-Sandbox-Id"] == "sandbox-1"
    assert kwargs["default_headers"]["X-Holaboss-Run-Id"] == "run-ctx-1"


def _single_plan(
    *,
    servers: tuple[ResolvedMcpServerConfig, ...] = (),
    tools: tuple[ResolvedMcpToolRef, ...] = (),
    output_schemas: dict[str, type[BaseModel]] | None = None,
) -> CompiledWorkspaceRuntimePlan:
    general_member = WorkspaceGeneralMemberConfig(
        id="workspace.general",
        model="gpt-5.2",
        prompt="You are concise.",
    )
    return CompiledWorkspaceRuntimePlan(
        workspace_id="workspace-1",
        mode="single",
        general_config=WorkspaceGeneralSingleConfig(type="single", agent=general_member),
        resolved_prompts={"workspace.general": "You are concise."},
        resolved_mcp_servers=servers,
        resolved_mcp_tool_refs=tools,
        workspace_mcp_catalog=(),
        resolved_output_schemas=output_schemas or {},
        config_checksum="checksum-1",
    )


def _team_plan() -> CompiledWorkspaceRuntimePlan:
    coordinator = WorkspaceGeneralMemberConfig(
        id="workspace.general.coordinator",
        model="gpt-5.2",
        prompt="Coordinate member output.",
    )
    member = WorkspaceGeneralMemberConfig(
        id="workspace.general.member",
        model="gpt-5.2",
        prompt="Be concise.",
    )
    return CompiledWorkspaceRuntimePlan(
        workspace_id="workspace-1",
        mode="team",
        general_config=WorkspaceGeneralTeamConfig(type="team", coordinator=coordinator, members=(member,)),
        resolved_prompts={
            "workspace.general.coordinator": "Coordinate member output.",
            "workspace.general.member": "Be concise.",
        },
        resolved_mcp_servers=(),
        resolved_mcp_tool_refs=(),
        workspace_mcp_catalog=(),
        resolved_output_schemas={},
        config_checksum="checksum-team-1",
    )


def test_persist_agno_session_message_writes_local_sqlite(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace-1"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    runner_module._persist_agno_session_message(
        workspace_dir=workspace_dir,
        session_id="main-session-1",
        role="user",
        text="hello",
        metadata={"input_id": "in-1"},
    )

    db_path = workspace_dir / ".holaboss" / "agno_sessions.db"
    assert db_path.is_file()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT session_id, role, text, metadata_json FROM agno_session_messages ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "main-session-1"
    assert rows[0][1] == "user"
    assert rows[0][2] == "hello"
    assert json.loads(rows[0][3]) == {"input_id": "in-1"}


def test_build_member_agent_attaches_agno_sqlite_db(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    sentinel_db = object()

    class _FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("sandbox_agent_runtime.runner._build_agno_sqlite_db", lambda workspace_id: sentinel_db)
    monkeypatch.setattr("agno.agent.Agent", _FakeAgent)

    plan = _single_plan()
    model_client_config = runner_module._ModelClientConfig(
        model_proxy_provider="openai_compatible",
        api_key="hbrt.v1.proxy-user-key",
    )

    runner_module._build_member_agent(
        member=plan.general_config.agent,
        model_id="gpt-5.2",
        compiled_plan=plan,
        tools=[],
        model_client_config=model_client_config,
        workspace_skills=None,
        skills=None,
    )

    assert captured["db"] is sentinel_db


def test_build_runner_from_team_plan_attaches_agno_sqlite_db(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    sentinel_db = object()

    class _FakeTeam:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("sandbox_agent_runtime.runner._build_agno_sqlite_db", lambda workspace_id: sentinel_db)
    monkeypatch.setattr("sandbox_agent_runtime.runner._build_member_agent", lambda **kwargs: "member-runner")
    monkeypatch.setattr("agno.team.Team", _FakeTeam)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )
    model_client_config = runner_module._ModelClientConfig(
        model_proxy_provider="openai_compatible",
        api_key="hbrt.v1.proxy-user-key",
    )

    runner_module._build_runner_from_plan(
        request=request,
        compiled_plan=_team_plan(),
        model_client_config=model_client_config,
        team_tools=[],
        member_tools=[],
    )

    assert captured["db"] is sentinel_db
    assert captured["members"] == ["member-runner"]


@pytest.mark.asyncio
async def test_execute_request_agno_persists_user_and_assistant_history(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return _single_plan()

    class _Event:
        def __init__(self, value: str) -> None:
            self.value = value

    class _CompletedChunk:
        event = _Event("TeamRunCompleted")
        content = "Persisted assistant output"

    class _FakeRunner:
        async def arun(self, instruction: str, **kwargs):
            del instruction, kwargs
            yield _CompletedChunk()

    def _fake_build_runner_from_plan(*, request, compiled_plan, model_client_config, team_tools, member_tools):
        del request, compiled_plan, model_client_config, team_tools, member_tools
        return _FakeRunner()

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_runner_from_plan",
        _fake_build_runner_from_plan,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="canonical-session-1",
        input_id="input-1",
        instruction="hello history",
        context=_runtime_exec_context(harness_session_id="harness-session-1"),
    )

    exit_code = await _execute_request(request)
    assert exit_code == 0
    assert capsys.readouterr().out

    db_path = Path(runner_module.WORKSPACE_ROOT) / "workspace-1" / ".holaboss" / "agno_sessions.db"
    assert db_path.is_file()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT role, text FROM agno_session_messages WHERE session_id = ? ORDER BY id ASC",
            ("harness-session-1",),
        ).fetchall()
    finally:
        conn.close()

    assert [row[0] for row in rows] == ["user", "assistant"]
    assert rows[0][1] == "hello history"
    assert "Persisted assistant output" in rows[1][1]


def test_build_opencode_runtime_config_maps_workspace_tools_and_schema() -> None:
    class _HealthPlan(BaseModel):
        checks: list[str]

    tools = (
        ResolvedMcpToolRef(tool_id="workspace.read_file", server_id="workspace", tool_name="read_file"),
        ResolvedMcpToolRef(tool_id="remote.lookup", server_id="remote", tool_name="lookup"),
    )
    plan = _single_plan(tools=tools, output_schemas={"workspace.general": _HealthPlan})
    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )

    config = _build_opencode_runtime_config(request=request, compiled_plan=plan, mcp_servers=())

    expected_tools = dict.fromkeys(runner_module._OPENCODE_DEFAULT_TOOLS, True)
    expected_tools.update({"workspace_read_file": True, "remote_lookup": True})
    assert config.tools == expected_tools
    assert config.workspace_tool_ids == ("workspace.read_file", "remote.lookup")
    assert config.output_schema_member_id == "workspace.general"
    assert config.output_schema_model is _HealthPlan
    assert config.output_format is not None
    assert config.output_format["type"] == "json_schema"
    assert "checks" in config.output_format["schema"]["properties"]


def test_workspace_sidecar_enabled_tool_ids_payload_only_includes_workspace_tools() -> None:
    tools = (
        ResolvedMcpToolRef(tool_id="workspace.echo", server_id="workspace", tool_name="echo"),
        ResolvedMcpToolRef(tool_id="remote.lookup", server_id="remote", tool_name="lookup"),
    )
    plan = _single_plan(tools=tools)
    tool_ids = runner_module._workspace_sidecar_enabled_tool_ids(compiled_plan=plan)
    assert tool_ids == ("workspace.echo",)

    payload = runner_module._sidecar_enabled_tool_ids_payload(plan)
    decoded = json.loads(base64.b64decode(payload.encode("utf-8")).decode("utf-8"))
    assert decoded == ["workspace.echo"]


def test_build_opencode_runtime_config_maps_workspace_tools_to_physical_server_ids() -> None:
    tools = (
        ResolvedMcpToolRef(tool_id="workspace.read_file", server_id="workspace", tool_name="read_file"),
        ResolvedMcpToolRef(tool_id="remote.lookup", server_id="remote", tool_name="lookup"),
    )
    servers = (
        ResolvedMcpServerConfig(
            server_id="workspace",
            type="local",
            command=("python", "-m", "sandbox_agent_runtime.workspace_mcp_sidecar"),
            timeout_ms=10000,
        ),
        ResolvedMcpServerConfig(server_id="remote", type="remote", url="https://example.com/mcp", timeout_ms=10000),
    )
    plan = _single_plan(servers=servers, tools=tools)
    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )

    config = _build_opencode_runtime_config(
        request=request,
        compiled_plan=plan,
        mcp_servers=(),
        tool_server_id_map={"workspace": "workspace__abc123", "remote": "remote"},
    )
    expected_tools = dict.fromkeys(runner_module._OPENCODE_DEFAULT_TOOLS, True)
    expected_tools.update({"workspace__abc123_read_file": True, "remote_lookup": True})
    assert config.tools == expected_tools


def test_mcp_server_id_map_assigns_stable_workspace_physical_id() -> None:
    servers = (
        ResolvedMcpServerConfig(
            server_id="workspace",
            type="local",
            command=("python", "-m", "sandbox_agent_runtime.workspace_mcp_sidecar"),
            timeout_ms=10000,
        ),
    )
    plan = _single_plan(servers=servers)
    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )

    mapping_one = runner_module._mcp_server_id_map(request=request, compiled_plan=plan, sandbox_id="sandbox-a")
    mapping_two = runner_module._mcp_server_id_map(request=request, compiled_plan=plan, sandbox_id="sandbox-a")
    mapping_other_workspace = runner_module._mcp_server_id_map(
        request=request.model_copy(update={"workspace_id": "workspace-2"}),
        compiled_plan=plan,
        sandbox_id="sandbox-a",
    )

    assert mapping_one["workspace"].startswith("workspace__")
    assert mapping_one["workspace"] != "workspace"
    assert mapping_one == mapping_two
    assert mapping_one["workspace"] != mapping_other_workspace["workspace"]


def test_build_opencode_runtime_config_defaults_to_builtin_tools_when_no_allowlisted_mcp_tools() -> None:
    plan = _single_plan(tools=())
    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )

    config = _build_opencode_runtime_config(request=request, compiled_plan=plan, mcp_servers=())
    assert config.tools == dict.fromkeys(runner_module._OPENCODE_DEFAULT_TOOLS, True)


def test_build_opencode_runtime_config_includes_workspace_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace_root = tmp_path / "workspace-root"
    workspace_dir = workspace_root / "workspace-1"
    skill_dir = workspace_dir / "skills" / "skill-creator"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Skill Creator\nUse this skill.\n", encoding="utf-8")
    (workspace_dir / "workspace.yaml").write_text(
        """
template_id: "workspace-1"
name: "Workspace"
skills:
  path: "skills"
  enabled:
    - "skill-creator"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sandbox_agent_runtime.runner.WORKSPACE_ROOT", str(workspace_root))

    plan = _single_plan(tools=())
    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )

    config = _build_opencode_runtime_config(request=request, compiled_plan=plan, mcp_servers=())
    assert config.workspace_skill_ids == ("skill-creator",)
    assert "Workspace skills are available in this run." not in config.system_prompt
    assert "skill-creator" not in config.system_prompt
    assert config.tools["skill"] is True
    assert config.tools["read"] is True


def test_build_runner_from_plan_passes_agno_skills_to_member_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace-root"
    workspace_dir = workspace_root / "workspace-1"
    skill_dir = workspace_dir / "skills" / "skill-installer"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Skill Installer\nUse this skill.\n", encoding="utf-8")
    (workspace_dir / "workspace.yaml").write_text(
        """
template_id: "workspace-1"
name: "Workspace"
skills:
  path: "skills"
  enabled:
    - "skill-installer"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sandbox_agent_runtime.runner.WORKSPACE_ROOT", str(workspace_root))

    captured: dict[str, object] = {}

    def _fake_build_member_agent(
        *,
        member,
        model_id,
        compiled_plan,
        tools,
        model_client_config,
        workspace_skills,
        skills,
    ):
        del member, model_id, compiled_plan, tools, model_client_config
        captured["workspace_skills"] = workspace_skills
        captured["skills"] = skills
        return "runner"

    monkeypatch.setattr("sandbox_agent_runtime.runner._build_member_agent", _fake_build_member_agent)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    model_client_config = runner_module._ModelClientConfig(
        model_proxy_provider="openai_compatible",
        api_key="hbrt.v1.proxy-user-key",
    )

    runner = runner_module._build_runner_from_plan(
        request=request,
        compiled_plan=_single_plan(),
        model_client_config=model_client_config,
        team_tools=[],
        member_tools=[],
    )
    assert runner == "runner"
    assert captured["workspace_skills"] is not None
    assert captured["skills"] is not None


def test_stage_workspace_skills_for_opencode_creates_discoverable_skill_dir(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace-1"
    skill_dir = workspace_dir / "skills" / "skill-creator"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Skill Creator\n", encoding="utf-8")
    (workspace_dir / "workspace.yaml").write_text(
        """
template_id: "workspace-1"
name: "Workspace"
skills:
  path: "skills"
  enabled:
    - "skill-creator"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    workspace_skills = runner_module._resolve_workspace_skills(workspace_dir=workspace_dir)
    assert workspace_skills is not None

    runner_module._stage_workspace_skills_for_opencode(
        workspace_dir=workspace_dir,
        workspace_skills=workspace_skills,
    )

    staged_skill = workspace_dir / ".opencode" / "skills" / "skill-creator" / "SKILL.md"
    assert staged_skill.is_file()
    assert "Skill Creator" in staged_skill.read_text(encoding="utf-8")
    runtime_staged_skill = Path(runner_module.WORKSPACE_ROOT) / ".opencode" / "skills" / "skill-creator" / "SKILL.md"
    assert runtime_staged_skill.is_file()
    assert "Skill Creator" in runtime_staged_skill.read_text(encoding="utf-8")


def test_stage_workspace_commands_for_opencode_creates_discoverable_commands_dir(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace-1"
    commands_dir = workspace_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "hello.md").write_text("---\ndescription: Hello\n---\nEcho hello.\n", encoding="utf-8")

    runner_module._stage_workspace_commands_for_opencode(workspace_dir=workspace_dir)

    staged_command = workspace_dir / ".opencode" / "commands" / "hello.md"
    assert staged_command.is_file()
    assert "Echo hello" in staged_command.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _noop_opencode_mcp_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*, client, mcp_servers):
        del client, mcp_servers
        return None

    async def _noop_session_exists(*, client, session_id):
        del client, session_id
        return True

    async def _noop_restart() -> None:
        return None

    def _noop_write_provider_config(*, provider_id, model_id, model_client_config):
        del provider_id, model_id, model_client_config
        return Path("opencode.json"), False

    def _noop_write_model_selection(*, provider_id, model_id):
        del provider_id, model_id
        return Path("opencode.json"), False

    monkeypatch.setattr("sandbox_agent_runtime.runner._ensure_opencode_mcp_servers", _noop)
    monkeypatch.setattr("sandbox_agent_runtime.runner._write_opencode_provider_config", _noop_write_provider_config)
    monkeypatch.setattr("sandbox_agent_runtime.runner._write_opencode_model_selection", _noop_write_model_selection)
    monkeypatch.setattr("sandbox_agent_runtime.runner._opencode_session_exists", _noop_session_exists)
    monkeypatch.setattr("sandbox_agent_runtime.runner._restart_opencode_sidecar", _noop_restart)


@pytest.mark.asyncio
async def test_ensure_opencode_mcp_servers_refreshes_missing_disconnected_changed_and_forced() -> None:
    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def json(self) -> dict[str, object]:
            return self._payload

    class _FakeClient:
        def __init__(self, status_payload: dict[str, object]) -> None:
            self._status_payload = status_payload
            self.posted_payloads: list[dict[str, object]] = []

        async def get(self, path: str, cast_to=None):
            del path, cast_to
            return _FakeResponse(self._status_payload)

        async def post(self, path: str, cast_to=None, body=None):
            del path, cast_to
            assert isinstance(body, dict)
            self.posted_payloads.append(body)
            return _FakeResponse({})

    client = _FakeClient({
        "stable": {
            "status": "connected",
            "config": {"type": "remote", "url": "https://stable.example/mcp", "enabled": True},
        },
        "changed": {
            "status": "connected",
            "config": {"type": "remote", "url": "https://old.example/mcp", "enabled": True},
        },
        "disconnected": {"status": "disconnected"},
        "forced": {"status": "connected"},
    })
    mcp_servers = (
        {"name": "stable", "config": {"type": "remote", "url": "https://stable.example/mcp", "enabled": True}},
        {"name": "changed", "config": {"type": "remote", "url": "https://new.example/mcp", "enabled": True}},
        {"name": "disconnected", "config": {"type": "remote", "url": "https://disc.example/mcp", "enabled": True}},
        {"name": "missing", "config": {"type": "remote", "url": "https://missing.example/mcp", "enabled": True}},
        {
            "name": "forced",
            "config": {"type": "remote", "url": "https://forced.example/mcp", "enabled": True},
            "_holaboss_force_refresh": True,
        },
    )

    await _ORIGINAL_ENSURE_OPENCODE_MCP_SERVERS(client=client, mcp_servers=mcp_servers)

    posted_names = [str(payload["name"]) for payload in client.posted_payloads]
    assert set(posted_names) == {"changed", "disconnected", "missing", "forced"}
    assert "stable" not in posted_names
    for payload in client.posted_payloads:
        assert set(payload.keys()) == {"name", "config"}


def test_build_opencode_runtime_config_preserves_mcp_server_payloads() -> None:
    tools = (ResolvedMcpToolRef(tool_id="workspace.lookup", server_id="workspace", tool_name="lookup"),)
    plan = _single_plan(tools=tools)
    mcp_servers = (
        {
            "name": "workspace",
            "config": {"type": "remote", "url": "http://127.0.0.1:9911/mcp", "enabled": True},
        },
    )
    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )

    config = _build_opencode_runtime_config(request=request, compiled_plan=plan, mcp_servers=mcp_servers)
    assert config.mcp_servers == mcp_servers


def test_opencode_provider_config_payload_uses_model_proxy_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(run_id="run-ctx-1", model_proxy_api_key="hbrt.v1.proxy-user-key"),
    )

    model_client_config = _resolve_model_client_config(request=request, model_proxy_provider="openai_compatible")
    payload = _opencode_provider_config_payload(
        provider_id="holaboss_proxy",
        model_id="gpt-5.1",
        model_client_config=model_client_config,
    )

    assert payload["model"] == "holaboss_proxy/gpt-5.1"
    provider = payload["provider"]["holaboss_proxy"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["baseURL"] == "http://sandbox-runtime:3060/api/v1/model-proxy/openai/v1"
    assert provider["options"]["apiKey"] == "hbrt.v1.proxy-user-key"
    assert provider["options"]["headers"]["X-API-Key"] == "hbrt.v1.proxy-user-key"
    assert provider["options"]["headers"]["X-Holaboss-Sandbox-Id"] == "sandbox-1"
    assert "X-Holaboss-Run-Id" not in provider["options"]["headers"]


def test_opencode_provider_config_payload_uses_anthropic_provider_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(run_id="run-ctx-1", model_proxy_api_key="hbrt.v1.proxy-user-key"),
    )

    model_client_config = _resolve_model_client_config(
        request=request,
        model_proxy_provider="anthropic_native",
        harness="opencode",
    )
    payload = _opencode_provider_config_payload(
        provider_id="anthropic",
        model_id="claude-3-7-sonnet-20250219",
        model_client_config=model_client_config,
    )

    provider = payload["provider"]["anthropic"]
    assert provider["npm"] == "@ai-sdk/anthropic"
    assert provider["options"]["baseURL"] == "http://sandbox-runtime:3060/api/v1/model-proxy/anthropic/v1"


def test_resolve_model_client_config_requires_sandbox_model_proxy_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOLABOSS_MODEL_PROXY_BASE_URL", raising=False)
    monkeypatch.delenv("SANDBOX_MODEL_PROXY_ENABLE_DIRECT_OPENAI_FALLBACK", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(run_id="run-ctx-1", model_proxy_api_key="hbrt.v1.proxy-user-key"),
    )

    with pytest.raises(
        RuntimeError,
        match=r"HOLABOSS_MODEL_PROXY_BASE_URL or runtime-config\.json:model_proxy_base_url is required",
    ):
        _resolve_model_client_config(request=request, model_proxy_provider="openai_compatible")


def test_map_opencode_event_extracts_text_from_message_updated_payload() -> None:
    raw_event = SimpleNamespace(
        type="message.updated",
        properties=SimpleNamespace(
            session_id="opencode-session-1",
            info={
                "parts": [
                    {"id": "text-part-1", "type": "text", "text": "Hello"},
                ]
            },
        ),
    )

    events = _map_opencode_event(
        raw_event=raw_event,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
    )

    assert events == [
        (
            "output_delta",
            {
                "delta": "Hello",
                "event": "message.updated",
                "source": "opencode",
                "part_id": "text-part-1",
                "part_type": "text",
                "delta_kind": "output",
            },
        )
    ]


def test_map_opencode_event_maps_reasoning_message_updated_part_to_thinking_delta() -> None:
    raw_event = SimpleNamespace(
        type="message.updated",
        properties=SimpleNamespace(
            session_id="opencode-session-1",
            info={
                "parts": [
                    {"id": "reason-part-1", "type": "reasoning", "text": "Plan first"},
                ]
            },
        ),
    )

    events = _map_opencode_event(
        raw_event=raw_event,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
    )

    assert events == [
        (
            "thinking_delta",
            {
                "delta": "Plan first",
                "event": "message.updated",
                "source": "opencode",
                "part_id": "reason-part-1",
                "part_type": "reasoning",
                "delta_kind": "thinking",
            },
        )
    ]


def test_map_opencode_event_uses_message_part_delta_for_incremental_streaming() -> None:
    raw_event = SimpleNamespace(
        type="message.part.updated",
        properties=SimpleNamespace(
            session_id="opencode-session-1",
            delta="Hel",
            part=SimpleNamespace(type="text", id="text-part-1", text="Hel", session_id="opencode-session-1"),
        ),
    )

    events = _map_opencode_event(
        raw_event=raw_event,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
    )

    assert events == [
        (
            "output_delta",
            {
                "delta": "Hel",
                "event": "message.part.updated",
                "source": "opencode",
                "part_id": "text-part-1",
                "part_type": "text",
                "delta_kind": "output",
            },
        )
    ]


def test_map_opencode_event_uses_reasoning_snapshot_for_part_delta() -> None:
    events = _map_opencode_event(
        raw_event=SimpleNamespace(
            type="message.part.delta",
            properties=SimpleNamespace(
                session_id="opencode-session-1",
                part_id="reason-part-1",
                delta="Think",
            ),
        ),
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
        part_type_snapshots={"reason-part-1": "reasoning"},
    )

    assert events == [
        (
            "thinking_delta",
            {
                "delta": "Think",
                "event": "message.part.delta",
                "source": "opencode",
                "part_id": "reason-part-1",
                "part_type": "reasoning",
                "delta_kind": "thinking",
            },
        )
    ]


def test_map_opencode_event_buffers_untyped_message_part_delta_until_part_type_is_known() -> None:
    part_type_snapshots: dict[str, str] = {}
    pending_part_deltas: dict[str, list[tuple[str, str]]] = {}

    raw_event = SimpleNamespace(
        type="message.part.delta",
        properties=SimpleNamespace(
            session_id="opencode-session-1",
            part_id="text-part-1",
            delta="Hello ",
        ),
    )

    events = _map_opencode_event(
        raw_event=raw_event,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
        part_type_snapshots=part_type_snapshots,
        pending_part_deltas=pending_part_deltas,
    )

    assert events == []
    assert pending_part_deltas == {"text-part-1": [("message.part.delta", "Hello ")]}

    part_type_snapshots["text-part-1"] = "text"
    raw_event_2 = SimpleNamespace(
        type="message.part.delta",
        properties=SimpleNamespace(
            session_id="opencode-session-1",
            part_id="text-part-1",
            delta="world",
        ),
    )

    events_2 = _map_opencode_event(
        raw_event=raw_event_2,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
        part_type_snapshots=part_type_snapshots,
        pending_part_deltas=pending_part_deltas,
    )

    assert events_2 == [
        (
            "output_delta",
            {
                "delta": "Hello ",
                "event": "message.part.delta",
                "source": "opencode",
                "part_id": "text-part-1",
                "part_type": "text",
                "delta_kind": "output",
            },
        ),
        (
            "output_delta",
            {
                "delta": "world",
                "event": "message.part.delta",
                "source": "opencode",
                "part_id": "text-part-1",
                "part_type": "text",
                "delta_kind": "output",
            },
        ),
    ]


def test_map_opencode_event_supports_message_part_delta_dict_properties_aliases() -> None:
    raw_event = SimpleNamespace(
        type="message.part.delta",
        properties={
            "sessionID": "opencode-session-1",
            "partID": "text-part-1",
            "delta": "world",
        },
    )

    events = _map_opencode_event(
        raw_event=raw_event,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
        part_type_snapshots={"text-part-1": "text"},
    )

    assert events == [
        (
            "output_delta",
            {
                "delta": "world",
                "event": "message.part.delta",
                "source": "opencode",
                "part_id": "text-part-1",
                "part_type": "text",
                "delta_kind": "output",
            },
        )
    ]


def test_map_opencode_event_maps_session_status_idle_to_run_completed() -> None:
    raw_event = SimpleNamespace(
        type="session.status",
        properties=SimpleNamespace(
            session_id="opencode-session-1",
            status=SimpleNamespace(type="idle"),
        ),
    )

    events = _map_opencode_event(
        raw_event=raw_event,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
    )

    assert events == [
        (
            "run_completed",
            {
                "status": "success",
                "event": "session.status",
                "session_status": "idle",
            },
        )
    ]


def test_map_opencode_event_treats_question_tool_call_as_waiting_user_terminal() -> None:
    raw_event = SimpleNamespace(
        type="message.part.updated",
        properties=SimpleNamespace(
            session_id="opencode-session-1",
            part=SimpleNamespace(
                type="tool",
                id="tool-part-1",
                tool="question",
                call_id="call-1",
                state=SimpleNamespace(
                    status="running",
                    input={
                        "questions": [
                            {
                                "question": "What are your top 1-3 outcomes?",
                                "header": "Top Outcomes",
                            }
                        ]
                    },
                    output=None,
                    error=None,
                ),
            ),
        ),
    )

    events = _map_opencode_event(
        raw_event=raw_event,
        target_session_id="opencode-session-1",
        text_snapshots={},
        tool_snapshots={},
    )

    assert events == [
        (
            "tool_call",
            {
                "phase": "started",
                "tool_name": "question",
                "error": False,
                "tool_args": {
                    "questions": [
                        {
                            "question": "What are your top 1-3 outcomes?",
                            "header": "Top Outcomes",
                        }
                    ]
                },
                "result": None,
                "event": "message.part.updated",
                "source": "opencode",
                "call_id": "call-1",
            },
        ),
        (
            "run_completed",
            {
                "status": "waiting_user",
                "event": "message.part.updated",
                "interaction_type": "question",
                "tool_name": "question",
                "question": {
                    "questions": [
                        {
                            "question": "What are your top 1-3 outcomes?",
                            "header": "Top Outcomes",
                        }
                    ]
                },
                "call_id": "call-1",
            },
        ),
    ]


def test_should_emit_opencode_event_filters_step_markers_and_prompt_echo() -> None:
    assert (
        _should_emit_opencode_event(
            event_type="thinking_delta",
            payload={"delta": "step-start", "source": "opencode"},
            instruction="hello",
        )
        is False
    )
    assert (
        _should_emit_opencode_event(
            event_type="thinking_delta",
            payload={"delta": "step-finish", "source": "opencode"},
            instruction="hello",
        )
        is False
    )
    assert (
        _should_emit_opencode_event(
            event_type="output_delta",
            payload={"delta": "hello", "source": "opencode"},
            instruction="hello",
        )
        is False
    )
    assert (
        _should_emit_opencode_event(
            event_type="output_delta",
            payload={"delta": "hello world", "source": "opencode"},
            instruction="hello",
        )
        is True
    )


@pytest.mark.asyncio
async def test_execute_request_opencode_harness_streams_and_completes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _FakeStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        def __init__(self) -> None:
            self.chat_kwargs: list[dict[str, object]] = []

        async def create(self, *, extra_body=None):
            return SimpleNamespace(id="opencode-session-1", extra_body=extra_body)

        async def chat(self, **kwargs):
            self.chat_kwargs.append(kwargs)
            return SimpleNamespace(id="msg-1")

    class _FakeEvent:
        async def list(self):
            part = SimpleNamespace(type="text", id="part-1", text="Hello world", session_id="opencode-session-1")
            events = [
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="opencode-session-1", part=part),
                ),
                SimpleNamespace(
                    type="session.status",
                    properties=SimpleNamespace(
                        session_id="opencode-session-1",
                        status=SimpleNamespace(type="idle"),
                    ),
                ),
            ]
            return _FakeStream(events)

    class _FakeClient:
        def __init__(self) -> None:
            self.session = _FakeSession()
            self.event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    fake_client = _FakeClient()
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: fake_client,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "output_delta", "run_completed"]
    assert events[1]["payload"]["provider_id"] == "openai"
    assert events[2]["payload"]["delta"] == "Hello world"
    assert events[3]["payload"]["status"] == "success"


@pytest.mark.asyncio
async def test_execute_request_opencode_harness_does_not_cancel_stream_reads_between_poll_ticks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _CancellationSensitiveStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)
            self.cancelled = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.cancelled or not self._events:
                raise StopAsyncIteration
            try:
                await asyncio.sleep(1.2)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        async def chat(self, **kwargs):
            del kwargs
            return SimpleNamespace(id="msg-1")

    class _FakeEvent:
        async def list(self):
            part = SimpleNamespace(type="text", id="part-1", text="Hello world", session_id="opencode-session-1")
            events = [
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="opencode-session-1", part=part),
                ),
                SimpleNamespace(
                    type="session.status",
                    properties=SimpleNamespace(
                        session_id="opencode-session-1",
                        status=SimpleNamespace(type="idle"),
                    ),
                ),
            ]
            return _CancellationSensitiveStream(events)

    class _FakeClient:
        session = _FakeSession()
        event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: _FakeClient(),
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "output_delta", "run_completed"]
    assert events[2]["payload"]["delta"] == "Hello world"
    assert events[3]["payload"]["status"] == "success"


@pytest.mark.asyncio
async def test_execute_request_opencode_harness_completes_when_question_tool_requests_user_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"question": True},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _FakeStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        async def chat(self, **kwargs):
            del kwargs
            return SimpleNamespace(id="msg-1")

    class _FakeEvent:
        async def list(self):
            question_part = SimpleNamespace(
                type="tool",
                id="tool-part-1",
                tool="question",
                call_id="call-1",
                state=SimpleNamespace(
                    status="running",
                    input={
                        "questions": [
                            {
                                "question": "What are your top 1-3 outcomes?",
                                "header": "Top Outcomes",
                            }
                        ]
                    },
                    output=None,
                    error=None,
                ),
                session_id="opencode-session-1",
            )
            return _FakeStream([
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="opencode-session-1", part=question_part),
                )
            ])

    class _FakeClient:
        session = _FakeSession()
        event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: _FakeClient(),
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "tool_call", "run_completed"]
    assert events[2]["payload"]["tool_name"] == "question"
    assert events[3]["payload"]["status"] == "waiting_user"
    assert events[3]["payload"]["interaction_type"] == "question"


@pytest.mark.asyncio
async def test_execute_request_opencode_harness_fails_fast_when_chat_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-4o-mini",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _HangingStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)
            raise StopAsyncIteration

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        async def chat(self, **kwargs):
            del kwargs
            raise json.JSONDecodeError("Expecting value", "", 0)

    class _FakeEvent:
        async def list(self):
            return _HangingStream()

    class _FakeClient:
        session = _FakeSession()
        event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: _FakeClient(),
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "run_failed"]
    assert "OpenCode chat request failed" in events[-1]["payload"]["message"]
    assert "Expecting value" in events[-1]["payload"]["message"]


@pytest.mark.asyncio
async def test_execute_request_opencode_harness_schema_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _StructuredOutput(BaseModel):
        steps: list[str]

    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_tool_ids=("read",),
            output_schema_member_id="workspace.general",
            output_schema_model=_StructuredOutput,
            output_format={"type": "json_schema", "schema": {"type": "object"}, "retryCount": 2},
            workspace_config_checksum="checksum-1",
        )

    class _FakeStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        def __init__(self) -> None:
            self.chat_kwargs: list[dict[str, object]] = []

        async def create(self, *, extra_body=None):
            return SimpleNamespace(id="opencode-session-1", extra_body=extra_body)

        async def chat(self, **kwargs):
            self.chat_kwargs.append(kwargs)
            return SimpleNamespace(id="msg-1")

        async def messages(self, session_id: str):
            del session_id
            return [
                SimpleNamespace(
                    info=SimpleNamespace(role="assistant"),
                    parts=[SimpleNamespace(type="text", text="not-json")],
                )
            ]

    class _FakeEvent:
        async def list(self):
            part = SimpleNamespace(type="text", id="part-1", text="not-json", session_id="opencode-session-1")
            return _FakeStream([
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="opencode-session-1", part=part),
                ),
                SimpleNamespace(
                    type="session.status",
                    properties=SimpleNamespace(
                        session_id="opencode-session-1",
                        status=SimpleNamespace(type="idle"),
                    ),
                ),
            ])

    class _FakeClient:
        def __init__(self) -> None:
            self.session = _FakeSession()
            self.event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    fake_client = _FakeClient()
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: fake_client,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "output_delta", "run_failed"]
    assert events[-1]["payload"]["type"] == "StructuredOutputValidationError"


@pytest.mark.asyncio
async def test_execute_request_opencode_harness_schema_validation_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _StructuredOutput(BaseModel):
        steps: list[str]

    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_tool_ids=("read",),
            output_schema_member_id="workspace.general",
            output_schema_model=_StructuredOutput,
            output_format={"type": "json_schema", "schema": {"type": "object"}, "retryCount": 2},
            workspace_config_checksum="checksum-1",
        )

    class _FakeStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        def __init__(self) -> None:
            self.chat_kwargs: list[dict[str, object]] = []

        async def create(self, *, extra_body=None):
            return SimpleNamespace(id="opencode-session-1", extra_body=extra_body)

        async def chat(self, **kwargs):
            self.chat_kwargs.append(kwargs)
            return SimpleNamespace(id="msg-1")

        async def messages(self, session_id: str):
            del session_id
            return [
                SimpleNamespace(
                    info=SimpleNamespace(role="assistant"),
                    parts=[SimpleNamespace(type="text", text='{"steps":["check readiness","add /healthz"]}')],
                )
            ]

    class _FakeEvent:
        async def list(self):
            part = SimpleNamespace(
                type="text",
                id="part-1",
                text='{"steps":["check readiness","add /healthz"]}',
                session_id="opencode-session-1",
            )
            return _FakeStream([
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="opencode-session-1", part=part),
                ),
                SimpleNamespace(
                    type="session.status",
                    properties=SimpleNamespace(
                        session_id="opencode-session-1",
                        status=SimpleNamespace(type="idle"),
                    ),
                ),
            ])

    class _FakeClient:
        def __init__(self) -> None:
            self.session = _FakeSession()
            self.event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    fake_client = _FakeClient()
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: fake_client,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "output_delta", "run_completed"]
    completed_payload = events[-1]["payload"]
    assert completed_payload["schema_member_id"] == "workspace.general"
    assert completed_payload["structured_output"] == {"steps": ["check readiness", "add /healthz"]}
    assert fake_client.session.chat_kwargs
    chat_call = fake_client.session.chat_kwargs[0]
    assert "extra_body" in chat_call
    assert chat_call["extra_body"] == {"format": {"type": "json_schema", "schema": {"type": "object"}, "retryCount": 2}}


@pytest.mark.asyncio
async def test_execute_request_run_failed_when_harness_value_invalid(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "invalid-harness")

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines
    event = json.loads(lines[-1])
    assert event["event_type"] == "run_failed"
    assert "SANDBOX_AGENT_HARNESS='invalid-harness'" in event["payload"]["message"]


@pytest.mark.asyncio
async def test_execute_request_opencode_harness_enriches_session_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _ErrorStream:
        def __init__(self) -> None:
            error = SimpleNamespace(
                name="APIError",
                data={
                    "message": "quota exceeded",
                    "status": 429,
                    "code": "insufficient_quota",
                    "providerID": "openai",
                },
            )
            self._events = [
                SimpleNamespace(
                    type="session.error",
                    properties=SimpleNamespace(session_id="opencode-session-1", error=error),
                )
            ]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        async def create(self, *, extra_body=None):
            return SimpleNamespace(id="opencode-session-1", extra_body=extra_body)

        async def chat(self, **kwargs):
            del kwargs
            return SimpleNamespace(id="msg-1")

    class _FakeEvent:
        async def list(self):
            return _ErrorStream()

    class _FakeClient:
        session = _FakeSession()
        event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: _FakeClient(),
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-session-1"),
    )
    exit_code = await _execute_request(request)
    assert exit_code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    assert [event["event_type"] for event in events] == ["run_claimed", "run_started", "run_failed"]
    failed = events[-1]["payload"]
    assert failed["error_name"] == "APIError"
    assert failed["status_code"] == 429
    assert failed["error_code"] == "insufficient_quota"
    assert failed["provider_id"] == "openai"


@pytest.mark.asyncio
async def test_execute_request_agno_uses_runtime_context_harness_session_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return _single_plan()

    class _Event:
        def __init__(self, value: str) -> None:
            self.value = value

    class _CompletedChunk:
        event = _Event("TeamRunCompleted")
        content = "Hello from team completion"

    seen_runner_session_ids: list[str] = []

    class _FakeRunner:
        async def arun(self, instruction: str, **kwargs):
            del instruction
            seen_runner_session_ids.append(str(kwargs.get("session_id")))
            yield _CompletedChunk()

    def _fake_build_runner_from_plan(*, request, compiled_plan, model_client_config, team_tools, member_tools):
        del request, compiled_plan, model_client_config, team_tools, member_tools
        return _FakeRunner()

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_runner_from_plan",
        _fake_build_runner_from_plan,
    )

    request_first = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="agno", harness_session_id="agno-main-1"),
    )
    request_second = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-2",
        input_id="input-2",
        instruction="hello again",
        context=_runtime_exec_context(
            run_id="run-2",
            model_proxy_api_key="hbrt.v1.run-token-2",
            harness="agno",
            harness_session_id="agno-main-1",
        ),
    )

    exit_code_first = await _execute_request(request_first)
    assert exit_code_first == 0
    capsys.readouterr()

    exit_code_second = await _execute_request(request_second)
    assert exit_code_second == 0

    assert seen_runner_session_ids == ["agno-main-1", "agno-main-1"]


@pytest.mark.asyncio
async def test_execute_request_opencode_uses_runtime_context_harness_session_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _FakeStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        def __init__(self) -> None:
            self.chat_session_ids: list[str] = []

        async def chat(self, **kwargs):
            self.chat_session_ids.append(str(kwargs.get("id")))
            return SimpleNamespace(id="msg-1")

    class _FakeEvent:
        async def list(self):
            part = SimpleNamespace(type="text", id="part-1", text="Hello world", session_id="opencode-main-1")
            events = [
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="opencode-main-1", part=part),
                ),
                SimpleNamespace(
                    type="session.status",
                    properties=SimpleNamespace(
                        session_id="opencode-main-1",
                        status=SimpleNamespace(type="idle"),
                    ),
                ),
            ]
            return _FakeStream(events)

    class _FakeClient:
        def __init__(self) -> None:
            self.session = _FakeSession()
            self.event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    fake_client = _FakeClient()
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: fake_client,
    )

    request_first = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-main-1"),
    )
    request_second = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-2",
        input_id="input-2",
        instruction="hello again",
        context=_runtime_exec_context(
            run_id="run-2",
            model_proxy_api_key="hbrt.v1.run-token-2",
            harness="opencode",
            harness_session_id="opencode-main-1",
        ),
    )

    exit_code_first = await _execute_request(request_first)
    assert exit_code_first == 0
    capsys.readouterr()

    exit_code_second = await _execute_request(request_second)
    assert exit_code_second == 0

    assert fake_client.session.chat_session_ids == ["opencode-main-1", "opencode-main-1"]


@pytest.mark.asyncio
async def test_execute_request_opencode_replaces_harness_session_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _FakeSession:
        def __init__(self) -> None:
            self.chat_session_ids: list[str] = []

        async def chat(self, **kwargs):
            self.chat_session_ids.append(str(kwargs.get("id")))
            return SimpleNamespace(id="msg-1")

    class _FakeStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeEvent:
        def __init__(self) -> None:
            self.list_calls = 0

        async def list(self):
            self.list_calls += 1
            part = SimpleNamespace(type="text", id="part-1", text="Hello world", session_id="unexpected-session")
            return _FakeStream([
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="unexpected-session", part=part),
                ),
                SimpleNamespace(
                    type="session.status",
                    properties=SimpleNamespace(
                        session_id="unexpected-session",
                        status=SimpleNamespace(type="idle"),
                    ),
                ),
            ])

    class _FakeClient:
        def __init__(self) -> None:
            self.session = _FakeSession()
            self.event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    created_ids: list[str] = []

    async def _fake_opencode_create_session() -> str:
        created_ids.append("unexpected-session")
        return "unexpected-session"

    async def _fake_opencode_session_exists(*, client, session_id):
        del client, session_id
        return False

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_create_session",
        _fake_opencode_create_session,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_session_exists",
        _fake_opencode_session_exists,
    )
    fake_client = _FakeClient()
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: fake_client,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-stale-1"),
    )
    assert await _execute_request(request) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    events = [json.loads(line) for line in lines]
    assert events[0]["event_type"] == "run_claimed"
    assert events[1]["event_type"] == "run_started"
    assert events[-1]["event_type"] == "run_completed"
    assert created_ids == ["unexpected-session"]
    assert fake_client.session.chat_session_ids == ["unexpected-session"]
    assert fake_client.event.list_calls == 1


@pytest.mark.asyncio
async def test_execute_request_opencode_model_selection_change_preserves_harness_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")

    async def _fake_compile_workspace_runtime_plan(*, workspace_dir, workspace_id):
        del workspace_dir, workspace_id
        return object()

    def _fake_build_opencode_runtime_config(*, request, compiled_plan, mcp_servers, tool_server_id_map=None):
        del request, compiled_plan, mcp_servers, tool_server_id_map
        return SimpleNamespace(
            provider_id="openai",
            model_id="gpt-5.2",
            mode="code",
            system_prompt="You are concise.",
            tools={"read": True},
            mcp_servers=(),
            workspace_config_checksum="checksum-1",
        )

    class _FakeStream:
        def __init__(self, events: list[object]) -> None:
            self._events = list(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._events:
                raise StopAsyncIteration
            return self._events.pop(0)

        async def aclose(self) -> None:
            return None

    class _FakeSession:
        def __init__(self) -> None:
            self.chat_session_ids: list[str] = []

        async def chat(self, **kwargs):
            self.chat_session_ids.append(str(kwargs.get("id")))
            return SimpleNamespace(id="msg-1")

    class _FakeEvent:
        def __init__(self) -> None:
            self.list_calls = 0

        async def list(self):
            self.list_calls += 1
            part = SimpleNamespace(type="text", id="part-1", text="Hello world", session_id="opencode-stale-1")
            return _FakeStream([
                SimpleNamespace(
                    type="message.part.updated",
                    properties=SimpleNamespace(session_id="opencode-stale-1", part=part),
                ),
                SimpleNamespace(
                    type="session.status",
                    properties=SimpleNamespace(
                        session_id="opencode-stale-1",
                        status=SimpleNamespace(type="idle"),
                    ),
                ),
            ])

    class _FakeClient:
        def __init__(self) -> None:
            self.session = _FakeSession()
            self.event = _FakeEvent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    model_selection_writes: list[bool] = [True]
    created_ids: list[str] = []

    def _fake_write_model_selection(*, provider_id, model_id):
        del provider_id, model_id
        changed = model_selection_writes.pop(0) if model_selection_writes else False
        return Path("opencode.json"), changed

    async def _fake_opencode_create_session() -> str:
        created_ids.append("unexpected-session")
        return "unexpected-session"

    async def _fake_opencode_session_exists(*, client, session_id):
        del client, session_id
        return True

    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._compile_workspace_runtime_plan",
        _fake_compile_workspace_runtime_plan,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._build_opencode_runtime_config",
        _fake_build_opencode_runtime_config,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._write_opencode_model_selection",
        _fake_write_model_selection,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_create_session",
        _fake_opencode_create_session,
    )
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_session_exists",
        _fake_opencode_session_exists,
    )
    fake_client = _FakeClient()
    monkeypatch.setattr(
        "sandbox_agent_runtime.runner._opencode_client_factory",
        lambda *, base_url: fake_client,
    )

    request = RunnerRequest(
        holaboss_user_id="user-1",
        workspace_id="workspace-1",
        session_id="session-1",
        input_id="input-1",
        instruction="hello",
        context=_runtime_exec_context(harness="opencode", harness_session_id="opencode-stale-1"),
    )
    assert await _execute_request(request) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip() and line.lstrip().startswith("{")]
    events = [json.loads(line) for line in lines]
    assert events[0]["event_type"] == "run_claimed"
    assert events[1]["event_type"] == "run_started"
    assert events[-1]["event_type"] == "run_completed"
    assert created_ids == []
    assert fake_client.session.chat_session_ids == ["opencode-stale-1"]
    assert fake_client.event.list_calls == 1
