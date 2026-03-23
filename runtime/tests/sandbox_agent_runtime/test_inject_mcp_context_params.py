# ruff: noqa: S101

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from sandbox_agent_runtime.runner import _inject_mcp_context_params


def _make_func(*, name: str, parameters: dict[str, Any] | None, entrypoint: Any) -> SimpleNamespace:
    return SimpleNamespace(name=name, parameters=parameters, entrypoint=entrypoint)


def _make_toolkit(functions: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(functions=functions)


async def _dummy_entrypoint(**kwargs: Any) -> dict[str, Any]:
    return kwargs


class TestInjectMcpContextParams:
    def test_injects_workspace_id_when_schema_declares_it(self) -> None:
        func = _make_func(
            name="create_post",
            parameters={
                "properties": {"workspaceId": {"type": "string"}, "content": {"type": "string"}},
                "required": ["content"],
            },
            entrypoint=_dummy_entrypoint,
        )
        toolkit = _make_toolkit({"create_post": func})

        _inject_mcp_context_params(mcp_tools=(toolkit,), workspace_id="ws-123")

        result = asyncio.get_event_loop().run_until_complete(func.entrypoint(content="hello"))
        assert result["workspaceId"] == "ws-123"
        assert result["content"] == "hello"

    def test_removes_workspace_id_from_schema(self) -> None:
        func = _make_func(
            name="create_post",
            parameters={
                "properties": {"workspaceId": {"type": "string"}, "content": {"type": "string"}},
                "required": ["workspaceId", "content"],
            },
            entrypoint=_dummy_entrypoint,
        )
        toolkit = _make_toolkit({"create_post": func})

        _inject_mcp_context_params(mcp_tools=(toolkit,), workspace_id="ws-123")

        assert "workspaceId" not in func.parameters["properties"]
        assert "workspaceId" not in func.parameters["required"]
        assert "content" in func.parameters["properties"]

    def test_does_not_touch_tools_without_workspace_id(self) -> None:
        original = _dummy_entrypoint
        func = _make_func(
            name="list_posts",
            parameters={"properties": {"status": {"type": "string"}}, "required": []},
            entrypoint=original,
        )
        toolkit = _make_toolkit({"list_posts": func})

        _inject_mcp_context_params(mcp_tools=(toolkit,), workspace_id="ws-123")

        assert func.entrypoint is original

    def test_setdefault_does_not_override_explicit_value(self) -> None:
        func = _make_func(
            name="create_post",
            parameters={"properties": {"workspaceId": {"type": "string"}}, "required": []},
            entrypoint=_dummy_entrypoint,
        )
        toolkit = _make_toolkit({"create_post": func})

        _inject_mcp_context_params(mcp_tools=(toolkit,), workspace_id="ws-123")

        result = asyncio.get_event_loop().run_until_complete(func.entrypoint(workspaceId="explicit"))
        assert result["workspaceId"] == "explicit"

    def test_handles_multiple_toolkits(self) -> None:
        func1 = _make_func(
            name="create_post",
            parameters={"properties": {"workspaceId": {"type": "string"}}, "required": []},
            entrypoint=_dummy_entrypoint,
        )
        func2 = _make_func(
            name="list_posts",
            parameters={"properties": {"status": {"type": "string"}}, "required": []},
            entrypoint=_dummy_entrypoint,
        )
        t1 = _make_toolkit({"create_post": func1})
        t2 = _make_toolkit({"list_posts": func2})

        _inject_mcp_context_params(mcp_tools=(t1, t2), workspace_id="ws-123")

        result = asyncio.get_event_loop().run_until_complete(func1.entrypoint())
        assert result["workspaceId"] == "ws-123"
        assert func2.entrypoint is _dummy_entrypoint

    def test_handles_empty_mcp_tools(self) -> None:
        _inject_mcp_context_params(mcp_tools=(), workspace_id="ws-123")

    def test_handles_none_parameters(self) -> None:
        func = _make_func(name="tool", parameters=None, entrypoint=_dummy_entrypoint)
        toolkit = _make_toolkit({"tool": func})

        _inject_mcp_context_params(mcp_tools=(toolkit,), workspace_id="ws-123")

        assert func.entrypoint is _dummy_entrypoint
