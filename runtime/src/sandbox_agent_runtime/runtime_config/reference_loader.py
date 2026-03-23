from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from pathlib import PurePosixPath
from typing import Any

from .errors import WorkspaceRuntimeConfigError

ReferenceReader = Callable[[str], Awaitable[str]]
_DEFAULT_PROMPT_FILE = "AGENTS.md"


class WorkspaceReferenceLoader:
    def __init__(self, *, reader: ReferenceReader) -> None:
        self._reader = reader

    async def resolve_prompts(self, *, config: Mapping[str, Any]) -> dict[str, str]:
        references = _collect_prompt_file_references(config)
        resolved: dict[str, str] = {}
        for path, config_path in references:
            normalized = _normalize_reference_path(path=path, config_path=config_path)
            if normalized in resolved:
                continue
            try:
                resolved[normalized] = await self._reader(normalized)
            except WorkspaceRuntimeConfigError:
                raise
            except FileNotFoundError as exc:
                if normalized == _DEFAULT_PROMPT_FILE:
                    continue
                raise WorkspaceRuntimeConfigError(
                    code="workspace_reference_missing",
                    path=config_path,
                    message=f"file '{normalized}' does not exist under workspace root",
                    hint="create the file or update workspace.yaml",
                ) from exc
        return resolved


def _collect_prompt_file_references(config: Mapping[str, Any]) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = [(_DEFAULT_PROMPT_FILE, _DEFAULT_PROMPT_FILE)]

    agents_value = config.get("agents")
    if isinstance(agents_value, list):
        for index, member in enumerate(agents_value):
            _append_prompt_reference(
                container=member,
                container_path=f"agents[{index}]",
                references=references,
            )
        return references

    if not isinstance(agents_value, Mapping):
        return references

    # New minimal single-object format: agents: {id, model, ...}
    if "id" in agents_value or "model" in agents_value:
        _append_prompt_reference(
            container=agents_value,
            container_path="agents",
            references=references,
        )
        return references

    # Legacy format retained for backward compatibility.
    general_value = agents_value.get("general")
    if not isinstance(general_value, Mapping):
        return references

    mode_value = general_value.get("type")
    if mode_value == "single":
        _append_prompt_reference(
            container=general_value.get("agent"),
            container_path="agents.general.agent",
            references=references,
        )
        return references

    if mode_value == "team":
        _append_prompt_reference(
            container=general_value.get("coordinator"),
            container_path="agents.general.coordinator",
            references=references,
        )
        members = general_value.get("members")
        if isinstance(members, list):
            for index, member in enumerate(members):
                _append_prompt_reference(
                    container=member,
                    container_path=f"agents.general.members[{index}]",
                    references=references,
                )

    return references


def _append_prompt_reference(
    *,
    container: Any,
    container_path: str,
    references: list[tuple[str, str]],
) -> None:
    if not isinstance(container, Mapping):
        return
    if "prompt" in container:
        raise WorkspaceRuntimeConfigError(
            code="workspace_prompt_inline_not_allowed",
            path=f"{container_path}.prompt",
            message="inline prompt content is not allowed; use AGENTS.md",
        )


def _normalize_reference_path(*, path: str, config_path: str) -> str:
    normalized = PurePosixPath(path)
    if normalized.is_absolute():
        raise WorkspaceRuntimeConfigError(
            code="workspace_reference_path_invalid",
            path=config_path,
            message=f"path '{path}' must be workspace-root relative",
        )
    if any(part in {"", ".", ".."} for part in normalized.parts):
        raise WorkspaceRuntimeConfigError(
            code="workspace_reference_path_invalid",
            path=config_path,
            message=f"path '{path}' must not contain empty, dot, or parent traversal segments",
        )
    return normalized.as_posix()
