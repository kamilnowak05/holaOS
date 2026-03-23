# ruff: noqa: S101
from __future__ import annotations

from sandbox_agent_runtime.runtime_config.models import (
    CompiledWorkspaceRuntimePlan,
    ResolvedApplication,
    ResolvedApplicationHealthCheck,
    ResolvedApplicationMcp,
    WorkspaceGeneralMemberConfig,
    WorkspaceGeneralSingleConfig,
)


def test_resolved_application_mcp_fields() -> None:
    mcp = ResolvedApplicationMcp(transport="http-sse", port=3099, path="/mcp")
    assert mcp.transport == "http-sse"
    assert mcp.port == 3099
    assert mcp.path == "/mcp"


def test_resolved_application_health_check() -> None:
    hc = ResolvedApplicationHealthCheck(path="/mcp/health", timeout_s=60, interval_s=5)
    assert hc.path == "/mcp/health"
    assert hc.timeout_s == 60
    assert hc.interval_s == 5


def test_resolved_application() -> None:
    mcp = ResolvedApplicationMcp(transport="http-sse", port=3099, path="/mcp")
    hc = ResolvedApplicationHealthCheck(path="/mcp/health", timeout_s=60, interval_s=5)
    app = ResolvedApplication(
        app_id="holaposter-ts-lite",
        mcp=mcp,
        health_check=hc,
        env_contract=("HOLABOSS_USER_ID",),
    )
    assert app.app_id == "holaposter-ts-lite"
    assert app.mcp.port == 3099
    assert app.health_check.path == "/mcp/health"
    assert "HOLABOSS_USER_ID" in app.env_contract


def test_compiled_plan_has_resolved_applications_and_allowlist() -> None:
    agent = WorkspaceGeneralMemberConfig(id="workspace.general", model="gpt-4o", prompt="")
    plan = CompiledWorkspaceRuntimePlan(
        workspace_id="ws-1",
        mode="single",
        general_config=WorkspaceGeneralSingleConfig(type="single", agent=agent),
        resolved_prompts={},
        resolved_mcp_servers=(),
        resolved_mcp_tool_refs=(),
        workspace_mcp_catalog=(),
        resolved_output_schemas={},
        config_checksum="abc",
        resolved_applications=(),
        mcp_tool_allowlist=frozenset(),
    )
    assert plan.resolved_applications == ()
    assert plan.mcp_tool_allowlist == frozenset()
