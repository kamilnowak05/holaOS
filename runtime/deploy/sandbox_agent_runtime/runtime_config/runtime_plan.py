from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import yaml

from .application_loader import WorkspaceApplicationLoader
from .errors import WorkspaceRuntimeConfigError
from .mcp_registry import WorkspaceMcpRegistryResolver
from .models import CompiledWorkspaceRuntimePlan
from .reference_loader import WorkspaceReferenceLoader
from .schema_registry import WorkspaceOutputSchemaResolver
from .team_loader import WorkspaceTeamLoader

ReferenceReader = Callable[[str], Awaitable[str]]


class WorkspaceRuntimePlanBuilder:
    def __init__(self) -> None:
        self._reference_loader_class = WorkspaceReferenceLoader
        self._team_loader = WorkspaceTeamLoader()
        self._mcp_registry_resolver = WorkspaceMcpRegistryResolver()
        self._schema_resolver = WorkspaceOutputSchemaResolver()
        self._application_loader = WorkspaceApplicationLoader()

    async def compile(
        self,
        *,
        workspace_id: str,
        workspace_yaml: str,
        reference_reader: ReferenceReader,
    ) -> CompiledWorkspaceRuntimePlan:
        config = _parse_workspace_yaml(workspace_yaml=workspace_yaml)

        reference_loader = self._reference_loader_class(reader=reference_reader)
        resolved_prompts_by_path = await reference_loader.resolve_prompts(config=config)
        general_config = self._team_loader.load(config=config, resolved_prompts_by_path=resolved_prompts_by_path)

        mcp_result = self._mcp_registry_resolver.resolve(config=config)
        resolved_schemas = self._schema_resolver.resolve(
            config=config,
            general_config=general_config,
            module_prefixes=mcp_result.module_prefixes,
        )

        resolved_prompts = _prompts_by_member_id(general_config=general_config)
        checksum = hashlib.sha256(workspace_yaml.encode("utf-8")).hexdigest()
        resolved_applications = await self._application_loader.load(
            config=config,
            reference_reader=reference_reader,
        )
        mcp_tool_allowlist = _read_mcp_allowlist(config)
        return CompiledWorkspaceRuntimePlan(
            workspace_id=workspace_id,
            mode=general_config.type,
            general_config=general_config,
            resolved_prompts=resolved_prompts,
            resolved_mcp_servers=mcp_result.resolved_servers,
            resolved_mcp_tool_refs=mcp_result.resolved_tool_refs,
            workspace_mcp_catalog=mcp_result.workspace_catalog,
            resolved_output_schemas=resolved_schemas,
            config_checksum=checksum,
            resolved_applications=resolved_applications,
            mcp_tool_allowlist=mcp_tool_allowlist,
        )


def _parse_workspace_yaml(*, workspace_yaml: str) -> Mapping[str, Any]:
    try:
        parsed = yaml.safe_load(workspace_yaml)
    except yaml.YAMLError as exc:
        raise WorkspaceRuntimeConfigError(
            code="workspace_config_invalid_yaml",
            path="workspace.yaml",
            message=f"invalid YAML: {exc}",
        ) from exc
    if not isinstance(parsed, Mapping):
        raise WorkspaceRuntimeConfigError(
            code="workspace_config_invalid_yaml",
            path="workspace.yaml",
            message="workspace.yaml must parse to a mapping object",
        )
    return parsed


def _prompts_by_member_id(*, general_config) -> dict[str, str]:
    if general_config.type == "single":
        return {general_config.agent.id: general_config.agent.prompt}
    output: dict[str, str] = {general_config.coordinator.id: general_config.coordinator.prompt}
    for member in general_config.members:
        output[member.id] = member.prompt
    return output


def _read_mcp_allowlist(config: Mapping[str, Any]) -> frozenset[str]:
    mcp_registry = config.get("mcp_registry")
    if not isinstance(mcp_registry, Mapping):
        return frozenset()
    allowlist = mcp_registry.get("allowlist")
    if not isinstance(allowlist, Mapping):
        return frozenset()
    tool_ids = allowlist.get("tool_ids")
    if not isinstance(tool_ids, list):
        return frozenset()
    return frozenset(str(t) for t in tool_ids if isinstance(t, str))
