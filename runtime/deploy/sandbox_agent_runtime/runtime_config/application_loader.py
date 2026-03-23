from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import yaml

from .errors import WorkspaceRuntimeConfigError
from .models import (
    ResolvedApplication,
    ResolvedApplicationHealthCheck,
    ResolvedApplicationLifecycle,
    ResolvedApplicationMcp,
)

ReferenceReader = Callable[[str], Awaitable[str]]


class WorkspaceApplicationLoader:
    async def load(
        self,
        *,
        config: Mapping[str, Any],
        reference_reader: ReferenceReader,
    ) -> tuple[ResolvedApplication, ...]:
        applications = config.get("applications")
        if not applications:
            return ()
        if not isinstance(applications, list):
            raise WorkspaceRuntimeConfigError(
                code="workspace_config_invalid_yaml",
                path="applications",
                message="applications must be a list",
            )

        seen_ids: set[str] = set()
        resolved: list[ResolvedApplication] = []

        for index, entry in enumerate(applications):
            if not isinstance(entry, Mapping):
                raise WorkspaceRuntimeConfigError(
                    code="workspace_config_invalid_yaml",
                    path=f"applications[{index}]",
                    message="each application entry must be a mapping",
                )
            app_id = str(entry.get("app_id") or "")
            config_path = str(entry.get("config_path") or "")

            if app_id in seen_ids:
                raise WorkspaceRuntimeConfigError(
                    code="app_duplicate_id",
                    path=f"applications[{index}].app_id",
                    message=f"duplicate app_id '{app_id}'",
                )

            try:
                raw_yaml = await reference_reader(config_path)
            except FileNotFoundError:
                raise WorkspaceRuntimeConfigError(
                    code="app_config_not_found",
                    path=f"applications[{index}].config_path",
                    message=f"app config not found: '{config_path}'",
                ) from None

            resolved.append(
                _parse_app_runtime_yaml(
                    raw_yaml=raw_yaml,
                    declared_app_id=app_id,
                    config_path=config_path,
                )
            )
            seen_ids.add(app_id)

        return tuple(resolved)


def _parse_app_runtime_yaml(
    *,
    raw_yaml: str,
    declared_app_id: str,
    config_path: str,
) -> ResolvedApplication:
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise WorkspaceRuntimeConfigError(
            code="app_config_invalid_yaml",
            path=config_path,
            message=f"invalid YAML: {exc}",
        ) from exc

    if not isinstance(data, Mapping):
        raise WorkspaceRuntimeConfigError(
            code="app_config_invalid_yaml",
            path=config_path,
            message="app.runtime.yaml must be a mapping",
        )

    yaml_app_id = str(data.get("app_id") or "")
    if yaml_app_id != declared_app_id:
        raise WorkspaceRuntimeConfigError(
            code="app_id_mismatch",
            path=config_path,
            message=f"app_id in yaml ('{yaml_app_id}') does not match declared app_id ('{declared_app_id}')",
        )

    # Parse mcp section
    mcp_raw = data.get("mcp") or {}
    mcp_port_raw = mcp_raw.get("port") if isinstance(mcp_raw, Mapping) else None
    if not mcp_port_raw:
        raise WorkspaceRuntimeConfigError(
            code="app_mcp_port_missing",
            path=f"{config_path}:mcp.port",
            message="mcp.port is required",
        )
    mcp = ResolvedApplicationMcp(
        transport=str(mcp_raw.get("transport") or "http-sse"),
        port=int(mcp_port_raw),
        path=str(mcp_raw.get("path") or "/mcp"),
    )

    # Parse healthchecks — prefer "mcp" key, fall back to "api" or first available
    healthchecks_raw = data.get("healthchecks") or {}
    hc_raw = None
    if isinstance(healthchecks_raw, Mapping):
        hc_raw = (
            healthchecks_raw.get("mcp") or healthchecks_raw.get("api") or next(iter(healthchecks_raw.values()), None)
        )
    if hc_raw and isinstance(hc_raw, Mapping):
        health_check = ResolvedApplicationHealthCheck(
            path=str(hc_raw.get("path") or "/health"),
            timeout_s=int(hc_raw.get("timeout_s") or 60),
            interval_s=int(hc_raw.get("interval_s") or 5),
        )
    else:
        health_check = ResolvedApplicationHealthCheck(path="/health")

    # Parse env_contract
    env_contract_raw = data.get("env_contract") or []
    env_contract = tuple(str(v) for v in env_contract_raw if isinstance(v, str))

    start_command = str(data.get("start") or "")

    # Parse lifecycle section (new module-driven process management)
    lifecycle_raw = data.get("lifecycle") or {}
    if isinstance(lifecycle_raw, Mapping):
        lifecycle = ResolvedApplicationLifecycle(
            setup=str(lifecycle_raw.get("setup") or ""),
            start=str(lifecycle_raw.get("start") or ""),
            stop=str(lifecycle_raw.get("stop") or ""),
        )
    else:
        lifecycle = ResolvedApplicationLifecycle()

    # Derive base_dir from config_path directory (e.g. "apps/myapp/app.runtime.yaml" → "apps/myapp")
    from pathlib import PurePosixPath

    config_dir = str(PurePosixPath(config_path).parent)
    # Use "." for workspace root so _start_app uses workspace_dir directly
    # Empty string means "fall back to apps/{app_id}/" (legacy default)
    base_dir = "." if config_dir == "." else config_dir

    return ResolvedApplication(
        app_id=declared_app_id,
        mcp=mcp,
        health_check=health_check,
        env_contract=env_contract,
        start_command=start_command,
        base_dir=base_dir,
        lifecycle=lifecycle,
    )
