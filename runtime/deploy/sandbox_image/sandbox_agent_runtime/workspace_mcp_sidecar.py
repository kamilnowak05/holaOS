from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from sandbox_agent_runtime.runtime_config.errors import WorkspaceRuntimeConfigError
from sandbox_agent_runtime.runtime_config.models import WorkspaceMcpCatalogEntry
from sandbox_agent_runtime.workspace_tool_loader import load_workspace_tools

logging.basicConfig(level=os.getenv("SANDBOX_AGENT_LOG_LEVEL", "INFO"))
logger = logging.getLogger("workspace_mcp_sidecar")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Workspace MCP sidecar for runtime-local workspace tools")
    parser.add_argument("--workspace-dir", required=True, help="Absolute workspace directory path")
    parser.add_argument("--catalog-json-base64", required=True, help="Base64-encoded JSON array of catalog entries")
    parser.add_argument(
        "--enabled-tool-ids-json-base64",
        default="",
        help="Base64-encoded JSON array of enabled workspace tool ids",
    )
    parser.add_argument("--workspace-id", default="", help="Workspace id bound to this sidecar process")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--server-name", default="workspace")
    return parser.parse_args(argv)


def _decode_catalog(encoded: str) -> tuple[WorkspaceMcpCatalogEntry, ...]:
    try:
        raw = base64.b64decode(encoded.encode("utf-8"), validate=True).decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_sidecar_start_failed",
            path="catalog_json_base64",
            message=f"invalid sidecar catalog payload: {exc}",
        ) from exc
    if not isinstance(payload, list):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_sidecar_start_failed",
            path="catalog_json_base64",
            message="catalog payload must decode to a list",
        )

    entries: list[WorkspaceMcpCatalogEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_sidecar_start_failed",
                path="catalog_json_base64",
                message="catalog entries must be objects",
            )
        entries.append(
            WorkspaceMcpCatalogEntry(
                tool_id=str(item.get("tool_id", "")),
                server_id=str(item.get("server_id", "workspace")),
                tool_name=str(item.get("tool_name", "")),
                module_path=str(item.get("module_path", "")),
                symbol_name=str(item.get("symbol_name", "")),
            )
        )
    return tuple(entries)


def _workspace_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_dir():
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_sidecar_start_failed",
            path="workspace_dir",
            message=f"workspace directory does not exist: {path}",
        )
    return path


def _decode_enabled_tool_ids(encoded: str) -> frozenset[str]:
    if not encoded:
        return frozenset()
    try:
        raw = base64.b64decode(encoded.encode("utf-8"), validate=True).decode("utf-8")
        payload = json.loads(raw)
    except Exception as exc:
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_sidecar_start_failed",
            path="enabled_tool_ids_json_base64",
            message=f"invalid enabled tool id payload: {exc}",
        ) from exc
    if not isinstance(payload, list):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_sidecar_start_failed",
            path="enabled_tool_ids_json_base64",
            message="enabled tool id payload must decode to a list",
        )
    tool_ids: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, str) or not item.strip():
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_sidecar_start_failed",
                path=f"enabled_tool_ids_json_base64[{index}]",
                message="enabled tool ids must be non-empty strings",
            )
        tool_ids.add(item.strip())
    return frozenset(tool_ids)


def _register_builtin_workspace_tools(
    *,
    mcp: FastMCP,
    workspace_dir: Path,
    workspace_id: str,
    enabled_tool_ids: frozenset[str],
) -> int:
    del mcp, workspace_dir, workspace_id, enabled_tool_ids
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    try:
        workspace_dir = _workspace_path(args.workspace_dir)
        catalog = _decode_catalog(args.catalog_json_base64)
        enabled_tool_ids = _decode_enabled_tool_ids(args.enabled_tool_ids_json_base64)
        loaded_tools = load_workspace_tools(workspace_dir=workspace_dir, catalog=catalog)

        mcp = FastMCP(
            args.server_name,
            host=args.host,
            port=args.port,
            json_response=True,
            stateless_http=True,
        )
        builtin_count = _register_builtin_workspace_tools(
            mcp=mcp,
            workspace_dir=workspace_dir,
            workspace_id=args.workspace_id,
            enabled_tool_ids=enabled_tool_ids,
        )
        for tool in loaded_tools:
            mcp.tool(name=tool.tool_name)(tool.callable_obj)

        logger.info(
            "Starting workspace MCP sidecar at %s:%s with %s tools",
            args.host,
            args.port,
            len(loaded_tools) + builtin_count,
            extra={
                "event": "workspace_mcp.sidecar.start",
                "outcome": "success",
                "workspace_id": args.workspace_id,
                "builtin_tool_count": builtin_count,
                "workspace_catalog_tool_count": len(loaded_tools),
            },
        )
        mcp.run(transport="streamable-http")
    except WorkspaceRuntimeConfigError:
        logger.exception("Workspace MCP sidecar configuration failure")
        return 2
    except Exception:
        logger.exception("Workspace MCP sidecar failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
