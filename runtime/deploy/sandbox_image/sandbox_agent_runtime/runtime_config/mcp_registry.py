from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .errors import WorkspaceRuntimeConfigError
from .models import ResolvedMcpServerConfig, ResolvedMcpToolRef, WorkspaceMcpCatalogEntry

_DEFAULT_TIMEOUT_MS = 10_000
_TOOL_ID_PATTERN = re.compile(r"^(?P<server>[A-Za-z0-9][A-Za-z0-9_-]*)\.(?P<tool>[A-Za-z0-9][A-Za-z0-9_-]*)$")
_WORKSPACE_SERVER_ID = "workspace"
_WORKSPACE_SIDECAR_COMMAND = ("python", "-m", "sandbox_agent_runtime.workspace_mcp_sidecar")


@dataclass(slots=True, frozen=True)
class McpRegistryCompileResult:
    module_prefixes: tuple[str, ...]
    resolved_servers: tuple[ResolvedMcpServerConfig, ...]
    resolved_tool_refs: tuple[ResolvedMcpToolRef, ...]
    workspace_catalog: tuple[WorkspaceMcpCatalogEntry, ...]


class WorkspaceMcpRegistryResolver:
    def resolve(self, *, config: Mapping[str, Any]) -> McpRegistryCompileResult:
        if isinstance(config.get("tool_registry"), Mapping):
            raise WorkspaceRuntimeConfigError(
                code="workspace_tool_registry_unsupported",
                path="tool_registry",
                message="tool_registry is no longer supported; use mcp_registry",
            )

        registry = config.get("mcp_registry")
        if not isinstance(registry, Mapping):
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_registry_missing",
                path="mcp_registry",
                message="missing object field 'mcp_registry'",
            )

        tool_refs = _read_allowlist(registry=registry)
        servers = _read_servers(registry=registry)
        catalog = _read_catalog(registry=registry)
        servers = _ensure_workspace_server_config(servers=servers)

        referenced_server_ids: list[str] = []
        seen_server_ids: set[str] = set()
        for index, tool_ref in enumerate(tool_refs):
            server = servers.get(tool_ref.server_id)
            if server is None:
                raise WorkspaceRuntimeConfigError(
                    code="workspace_mcp_server_unknown",
                    path=f"mcp_registry.allowlist.tool_ids[{index}]",
                    message=f"unknown MCP server '{tool_ref.server_id}' for tool '{tool_ref.tool_id}'",
                    hint="add server config under mcp_registry.servers",
                )
            if not server.enabled:
                raise WorkspaceRuntimeConfigError(
                    code="workspace_mcp_server_unknown",
                    path=f"mcp_registry.allowlist.tool_ids[{index}]",
                    message=f"MCP server '{tool_ref.server_id}' is disabled for tool '{tool_ref.tool_id}'",
                )
            if tool_ref.server_id not in seen_server_ids:
                referenced_server_ids.append(tool_ref.server_id)
                seen_server_ids.add(tool_ref.server_id)

        workspace_catalog: list[WorkspaceMcpCatalogEntry] = []
        for index, tool_ref in enumerate(tool_refs):
            if tool_ref.server_id != _WORKSPACE_SERVER_ID:
                continue
            catalog_entry = catalog.get(tool_ref.tool_id)
            if catalog_entry is None:
                raise WorkspaceRuntimeConfigError(
                    code="workspace_mcp_catalog_missing",
                    path=f"mcp_registry.allowlist.tool_ids[{index}]",
                    message=f"workspace tool '{tool_ref.tool_id}' is missing catalog entry in mcp_registry.catalog",
                )
            workspace_catalog.append(
                WorkspaceMcpCatalogEntry(
                    tool_id=tool_ref.tool_id,
                    server_id=tool_ref.server_id,
                    tool_name=tool_ref.tool_name,
                    module_path=catalog_entry.module_path,
                    symbol_name=catalog_entry.symbol_name,
                )
            )

        module_prefixes = _collect_module_prefixes(entries=workspace_catalog)
        resolved_servers = tuple(servers[server_id].to_resolved() for server_id in referenced_server_ids)

        return McpRegistryCompileResult(
            module_prefixes=module_prefixes,
            resolved_servers=resolved_servers,
            resolved_tool_refs=tuple(tool_refs),
            workspace_catalog=tuple(workspace_catalog),
        )


@dataclass(slots=True, frozen=True)
class _ServerConfig:
    server_id: str
    type: str
    command: tuple[str, ...]
    url: str | None
    headers: tuple[tuple[str, str], ...]
    environment: tuple[tuple[str, str], ...]
    timeout_ms: int
    enabled: bool

    def to_resolved(self) -> ResolvedMcpServerConfig:
        return ResolvedMcpServerConfig(
            server_id=self.server_id,
            type=self.type,  # type: ignore[arg-type]
            command=self.command,
            url=self.url,
            headers=self.headers,
            environment=self.environment,
            timeout_ms=self.timeout_ms,
        )


@dataclass(slots=True, frozen=True)
class _CatalogEntry:
    module_path: str
    symbol_name: str


def _read_allowlist(*, registry: Mapping[str, Any]) -> tuple[ResolvedMcpToolRef, ...]:
    allowlist = registry.get("allowlist")
    if not isinstance(allowlist, Mapping):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_registry_missing",
            path="mcp_registry.allowlist",
            message="missing object field 'mcp_registry.allowlist'",
        )

    tool_ids = allowlist.get("tool_ids")
    if not isinstance(tool_ids, list):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_tool_id_invalid",
            path="mcp_registry.allowlist.tool_ids",
            message="expected list field 'tool_ids'",
        )

    seen: set[str] = set()
    refs: list[ResolvedMcpToolRef] = []
    for index, value in enumerate(tool_ids):
        if not isinstance(value, str) or not value.strip():
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_tool_id_invalid",
                path=f"mcp_registry.allowlist.tool_ids[{index}]",
                message="tool id must be a non-empty string",
            )
        token = value.strip()
        parsed = _parse_tool_id(token=token)
        if parsed is None:
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_tool_id_invalid",
                path=f"mcp_registry.allowlist.tool_ids[{index}]",
                message=f"tool id '{token}' must match strict 'server.tool' format",
            )
        if token in seen:
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_tool_id_invalid",
                path=f"mcp_registry.allowlist.tool_ids[{index}]",
                message=f"duplicate MCP tool id '{token}'",
            )
        seen.add(token)
        refs.append(
            ResolvedMcpToolRef(
                tool_id=token,
                server_id=parsed[0],
                tool_name=parsed[1],
            )
        )
    return tuple(refs)


def _read_servers(*, registry: Mapping[str, Any]) -> dict[str, _ServerConfig]:
    servers = registry.get("servers")
    if not isinstance(servers, Mapping):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_registry_missing",
            path="mcp_registry.servers",
            message="missing object field 'mcp_registry.servers'",
        )

    parsed: dict[str, _ServerConfig] = {}
    for server_id, value in servers.items():
        if not isinstance(server_id, str) or not server_id.strip():
            continue
        server_key = server_id.strip()
        if not isinstance(value, Mapping):
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_server_unknown",
                path=f"mcp_registry.servers.{server_key}",
                message="server definition must be an object",
            )

        server_type_raw = value.get("type")
        if not isinstance(server_type_raw, str):
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_server_unknown",
                path=f"mcp_registry.servers.{server_key}.type",
                message="server type must be 'local' or 'remote'",
            )
        server_type = server_type_raw.strip()
        if server_type not in {"local", "remote"}:
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_server_unknown",
                path=f"mcp_registry.servers.{server_key}.type",
                message="server type must be 'local' or 'remote'",
            )

        enabled_raw = value.get("enabled")
        enabled = True if enabled_raw is None else bool(enabled_raw)

        timeout_ms_raw = value.get("timeout_ms")
        timeout_ms = _parse_timeout_ms(
            value=timeout_ms_raw,
            path=f"mcp_registry.servers.{server_key}.timeout_ms",
        )

        headers = _parse_str_mapping(
            value=value.get("headers"),
            path=f"mcp_registry.servers.{server_key}.headers",
        )
        environment = _parse_str_mapping(
            value=value.get("environment"),
            path=f"mcp_registry.servers.{server_key}.environment",
        )

        if server_type == "local":
            command_value = value.get("command")
            command = _parse_command(
                value=command_value,
                path=f"mcp_registry.servers.{server_key}.command",
            )
            parsed[server_key] = _ServerConfig(
                server_id=server_key,
                type="local",
                command=command,
                url=None,
                headers=headers,
                environment=environment,
                timeout_ms=timeout_ms,
                enabled=enabled,
            )
            continue

        url_raw = value.get("url")
        if not isinstance(url_raw, str) or not url_raw.strip():
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_server_unknown",
                path=f"mcp_registry.servers.{server_key}.url",
                message="remote server requires non-empty string field 'url'",
            )
        parsed[server_key] = _ServerConfig(
            server_id=server_key,
            type="remote",
            command=(),
            url=url_raw.strip(),
            headers=headers,
            environment=environment,
            timeout_ms=timeout_ms,
            enabled=enabled,
        )

    return parsed


def _read_catalog(*, registry: Mapping[str, Any]) -> dict[str, _CatalogEntry]:
    raw_catalog = registry.get("catalog")
    if raw_catalog is None:
        return {}
    if not isinstance(raw_catalog, Mapping):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_catalog_entry_invalid",
            path="mcp_registry.catalog",
            message="catalog must be an object when provided",
        )

    parsed: dict[str, _CatalogEntry] = {}
    for tool_id, entry in raw_catalog.items():
        if not isinstance(tool_id, str) or not tool_id.strip():
            continue
        path = f"mcp_registry.catalog.{tool_id}"
        if not isinstance(entry, Mapping):
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_catalog_entry_invalid",
                path=path,
                message="catalog entry must be an object",
            )
        module_path = entry.get("module_path")
        symbol_name = entry.get("symbol")
        if not isinstance(module_path, str) or not module_path.strip():
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_catalog_entry_invalid",
                path=f"{path}.module_path",
                message="catalog entry requires non-empty 'module_path'",
            )
        if not isinstance(symbol_name, str) or not symbol_name.strip():
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_catalog_entry_invalid",
                path=f"{path}.symbol",
                message="catalog entry requires non-empty 'symbol'",
            )
        parsed[tool_id.strip()] = _CatalogEntry(
            module_path=module_path.strip(),
            symbol_name=symbol_name.strip(),
        )
    return parsed


def _parse_tool_id(*, token: str) -> tuple[str, str] | None:
    match = _TOOL_ID_PATTERN.fullmatch(token)
    if match is None:
        return None
    return match.group("server"), match.group("tool")


def _parse_command(*, value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_server_unknown",
            path=path,
            message="expected non-empty list command",
        )
    command: list[str] = []
    for index, token in enumerate(value):
        if not isinstance(token, str) or not token.strip():
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_server_unknown",
                path=f"{path}[{index}]",
                message="command tokens must be non-empty strings",
            )
        command.append(token.strip())
    if not command:
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_server_unknown",
            path=path,
            message="command list must not be empty",
        )
    return tuple(command)


def _parse_str_mapping(*, value: Any, path: str) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_server_unknown",
            path=path,
            message="expected mapping object",
        )
    items: list[tuple[str, str]] = []
    for key, mapped_value in value.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(mapped_value, str):
            raise WorkspaceRuntimeConfigError(
                code="workspace_mcp_server_unknown",
                path=f"{path}.{key}",
                message="mapping values must be strings",
            )
        items.append((key.strip(), mapped_value))
    return tuple(items)


def _parse_timeout_ms(*, value: Any, path: str) -> int:
    if value is None:
        return _DEFAULT_TIMEOUT_MS
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_server_unknown",
            path=path,
            message="timeout_ms must be an integer when provided",
        )
    if value <= 0:
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_server_unknown",
            path=path,
            message="timeout_ms must be greater than 0",
        )
    return value


def _collect_module_prefixes(*, entries: list[WorkspaceMcpCatalogEntry]) -> tuple[str, ...]:
    prefixes: set[str] = set()
    for entry in entries:
        parts = entry.module_path.split(".")
        for index in range(1, len(parts) + 1):
            prefixes.add(".".join(parts[:index]))
    return tuple(sorted(prefixes))


def _ensure_workspace_server_config(*, servers: dict[str, _ServerConfig]) -> dict[str, _ServerConfig]:
    workspace_server = servers.get(_WORKSPACE_SERVER_ID)
    if workspace_server is None:
        merged = dict(servers)
        merged[_WORKSPACE_SERVER_ID] = _ServerConfig(
            server_id=_WORKSPACE_SERVER_ID,
            type="local",
            command=_WORKSPACE_SIDECAR_COMMAND,
            url=None,
            headers=(),
            environment=(),
            timeout_ms=_DEFAULT_TIMEOUT_MS,
            enabled=True,
        )
        return merged
    if workspace_server.type != "local":
        raise WorkspaceRuntimeConfigError(
            code="workspace_mcp_server_unknown",
            path=f"mcp_registry.servers.{_WORKSPACE_SERVER_ID}.type",
            message="workspace MCP server must be local",
        )
    if workspace_server.command != _WORKSPACE_SIDECAR_COMMAND:
        normalized = replace(workspace_server, command=_WORKSPACE_SIDECAR_COMMAND)
        merged = dict(servers)
        merged[_WORKSPACE_SERVER_ID] = normalized
        return merged
    return servers
