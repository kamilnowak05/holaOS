from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import WorkspaceRuntimeConfigError
from .models import (
    WorkspaceGeneralConfig,
    WorkspaceGeneralMemberConfig,
    WorkspaceGeneralSingleConfig,
    WorkspaceGeneralTeamConfig,
)

_DEFAULT_PROMPT_FILE = "AGENTS.md"


class WorkspaceTeamLoader:
    def load(
        self,
        *,
        config: Mapping[str, Any],
        resolved_prompts_by_path: Mapping[str, str],
    ) -> WorkspaceGeneralConfig:
        agents_value = config.get("agents")
        if isinstance(agents_value, list):
            return self._load_from_flat_agents_list(
                agents=agents_value,
                resolved_prompts_by_path=resolved_prompts_by_path,
            )

        if isinstance(agents_value, Mapping):
            # New minimal format: agents: {id: ..., model: ...}
            if "id" in agents_value or "model" in agents_value:
                member = self._parse_member(
                    value=agents_value,
                    base_path="agents",
                    resolved_prompts_by_path=resolved_prompts_by_path,
                )
                return WorkspaceGeneralSingleConfig(type="single", agent=member)

            # Legacy format retained for backward compatibility.
            general_value = agents_value.get("general")
            if isinstance(general_value, Mapping):
                return self._load_from_legacy_general(
                    general_value=general_value,
                    resolved_prompts_by_path=resolved_prompts_by_path,
                )

        raise WorkspaceRuntimeConfigError(
            code="workspace_general_missing",
            path="agents",
            message="missing field 'agents'",
            hint=(
                "set 'agents' to a non-empty list (or object) of members with at least id/model; "
                f"workspace instructions come from root '{_DEFAULT_PROMPT_FILE}' when present"
            ),
        )

    def _load_from_flat_agents_list(
        self,
        *,
        agents: list[Any],
        resolved_prompts_by_path: Mapping[str, str],
    ) -> WorkspaceGeneralConfig:
        if not agents:
            raise WorkspaceRuntimeConfigError(
                code="workspace_general_missing",
                path="agents",
                message="'agents' must include at least one agent",
            )

        members: list[WorkspaceGeneralMemberConfig] = []
        seen_ids: set[str] = set()
        for index, entry in enumerate(agents):
            if not isinstance(entry, Mapping):
                raise WorkspaceRuntimeConfigError(
                    code="workspace_general_missing",
                    path=f"agents[{index}]",
                    message="agent entry must be an object",
                )
            member = self._parse_member(
                value=entry,
                base_path=f"agents[{index}]",
                resolved_prompts_by_path=resolved_prompts_by_path,
            )
            if member.id in seen_ids:
                raise WorkspaceRuntimeConfigError(
                    code="workspace_team_member_id_duplicate",
                    path=f"agents[{index}].id",
                    message=f"duplicate member id '{member.id}'",
                    hint="all agent ids must be unique",
                )
            seen_ids.add(member.id)
            members.append(member)

        return self._build_runtime_config_from_members(members)

    def _load_from_legacy_general(
        self,
        *,
        general_value: Mapping[str, Any],
        resolved_prompts_by_path: Mapping[str, str],
    ) -> WorkspaceGeneralConfig:
        mode_value = general_value.get("type")
        if not isinstance(mode_value, str) or mode_value not in {"single", "team"}:
            raise WorkspaceRuntimeConfigError(
                code="workspace_general_type_invalid",
                path="agents.general.type",
                message="expected 'single' or 'team'",
                hint="set agents.general.type to either 'single' or 'team'",
            )

        if mode_value == "single":
            agent_value = general_value.get("agent")
            if not isinstance(agent_value, Mapping):
                raise WorkspaceRuntimeConfigError(
                    code="workspace_general_missing",
                    path="agents.general.agent",
                    message="single mode requires object field 'agent'",
                )
            member = self._parse_member(
                value=agent_value,
                base_path="agents.general.agent",
                resolved_prompts_by_path=resolved_prompts_by_path,
            )
            return WorkspaceGeneralSingleConfig(type="single", agent=member)

        coordinator_value = general_value.get("coordinator")
        members_value = general_value.get("members")
        if not isinstance(coordinator_value, Mapping):
            raise WorkspaceRuntimeConfigError(
                code="workspace_general_missing",
                path="agents.general.coordinator",
                message="team mode requires object field 'coordinator'",
            )
        if not isinstance(members_value, list) or not members_value:
            raise WorkspaceRuntimeConfigError(
                code="workspace_general_missing",
                path="agents.general.members",
                message="team mode requires at least one member in 'members'",
            )

        coordinator = self._parse_member(
            value=coordinator_value,
            base_path="agents.general.coordinator",
            resolved_prompts_by_path=resolved_prompts_by_path,
        )

        members: list[WorkspaceGeneralMemberConfig] = []
        seen_ids: set[str] = {coordinator.id}
        for index, member_value in enumerate(members_value):
            if not isinstance(member_value, Mapping):
                raise WorkspaceRuntimeConfigError(
                    code="workspace_general_missing",
                    path=f"agents.general.members[{index}]",
                    message="member entry must be an object",
                )
            member = self._parse_member(
                value=member_value,
                base_path=f"agents.general.members[{index}]",
                resolved_prompts_by_path=resolved_prompts_by_path,
            )
            if member.id in seen_ids:
                raise WorkspaceRuntimeConfigError(
                    code="workspace_team_member_id_duplicate",
                    path=f"agents.general.members[{index}].id",
                    message=f"duplicate member id '{member.id}'",
                    hint="all coordinator/member ids must be unique",
                )
            seen_ids.add(member.id)
            members.append(member)

        return WorkspaceGeneralTeamConfig(type="team", coordinator=coordinator, members=tuple(members))

    @staticmethod
    def _build_runtime_config_from_members(
        members: list[WorkspaceGeneralMemberConfig],
    ) -> WorkspaceGeneralConfig:
        if len(members) == 1:
            return WorkspaceGeneralSingleConfig(type="single", agent=members[0])
        return WorkspaceGeneralTeamConfig(type="team", coordinator=members[0], members=tuple(members[1:]))

    @staticmethod
    def _parse_member(
        *,
        value: Mapping[str, Any],
        base_path: str,
        resolved_prompts_by_path: Mapping[str, str],
    ) -> WorkspaceGeneralMemberConfig:
        member_id = _required_str(value=value, key="id", path=f"{base_path}.id")
        model = _required_str(value=value, key="model", path=f"{base_path}.model")

        if "prompt" in value:
            raise WorkspaceRuntimeConfigError(
                code="workspace_prompt_inline_not_allowed",
                path=f"{base_path}.prompt",
                message="inline prompt content is not allowed; use AGENTS.md",
            )
        prompt = resolved_prompts_by_path.get(_DEFAULT_PROMPT_FILE, "")

        role = _optional_str(value=value, key="role", path=f"{base_path}.role")
        schema_id = _optional_str(value=value, key="schema_id", path=f"{base_path}.schema_id")
        schema_module_path = _optional_str(
            value=value,
            key="schema_module_path",
            path=f"{base_path}.schema_module_path",
        )
        if schema_id and schema_module_path:
            raise WorkspaceRuntimeConfigError(
                code="workspace_schema_field_conflict",
                path=base_path,
                message="use only one of 'schema_id' or 'schema_module_path'",
                hint="remove one schema field from this member",
            )

        return WorkspaceGeneralMemberConfig(
            id=member_id,
            model=model,
            prompt=prompt,
            config_path=base_path,
            role=role,
            schema_id=schema_id,
            schema_module_path=schema_module_path,
        )


def _required_str(*, value: Mapping[str, Any], key: str, path: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise WorkspaceRuntimeConfigError(
            code="workspace_general_missing",
            path=path,
            message=f"expected non-empty string field '{key}'",
        )
    return raw.strip()


def _optional_str(*, value: Mapping[str, Any], key: str, path: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise WorkspaceRuntimeConfigError(
            code="workspace_general_missing",
            path=path,
            message=f"expected non-empty string field '{key}' when provided",
        )
    return raw.strip()
