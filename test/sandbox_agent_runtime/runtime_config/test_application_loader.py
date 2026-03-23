# ruff: noqa: S101
from __future__ import annotations

import pytest
from sandbox_agent_runtime.runtime_config.application_loader import WorkspaceApplicationLoader
from sandbox_agent_runtime.runtime_config.errors import WorkspaceRuntimeConfigError

_APP_YAML = """\
app_id: holaposter-ts-lite

healthchecks:
  mcp:
    path: /mcp/health
    timeout_s: 60
    interval_s: 5

mcp:
  transport: http-sse
  port: 3099
  path: /mcp

env_contract:
  - HOLABOSS_USER_ID
  - PLATFORM_INTEGRATION_TOKEN
"""

_CONFIG_WITH_APPS = {
    "applications": [{"app_id": "holaposter-ts-lite", "config_path": "apps/holaposter-ts-lite/app.runtime.yaml"}]
}
_CONFIG_NO_APPS: dict = {}


def _reader(files: dict[str, str]):
    async def _read(path: str) -> str:
        if path not in files:
            raise FileNotFoundError(path)
        return files[path]

    return _read


@pytest.mark.asyncio
async def test_no_applications_returns_empty() -> None:
    loader = WorkspaceApplicationLoader()
    result = await loader.load(config=_CONFIG_NO_APPS, reference_reader=_reader({}))
    assert result == ()


@pytest.mark.asyncio
async def test_loads_valid_application() -> None:
    loader = WorkspaceApplicationLoader()
    files = {"apps/holaposter-ts-lite/app.runtime.yaml": _APP_YAML}
    result = await loader.load(config=_CONFIG_WITH_APPS, reference_reader=_reader(files))
    assert len(result) == 1
    app = result[0]
    assert app.app_id == "holaposter-ts-lite"
    assert app.mcp.port == 3099
    assert app.mcp.path == "/mcp"
    assert app.mcp.transport == "http-sse"
    assert app.health_check.path == "/mcp/health"
    assert app.health_check.timeout_s == 60
    assert "HOLABOSS_USER_ID" in app.env_contract


@pytest.mark.asyncio
async def test_config_not_found_raises() -> None:
    loader = WorkspaceApplicationLoader()
    with pytest.raises(WorkspaceRuntimeConfigError) as exc_info:
        await loader.load(config=_CONFIG_WITH_APPS, reference_reader=_reader({}))
    assert exc_info.value.code == "app_config_not_found"


@pytest.mark.asyncio
async def test_app_id_mismatch_raises() -> None:
    bad_yaml = _APP_YAML.replace("app_id: holaposter-ts-lite", "app_id: wrong-name")
    loader = WorkspaceApplicationLoader()
    files = {"apps/holaposter-ts-lite/app.runtime.yaml": bad_yaml}
    with pytest.raises(WorkspaceRuntimeConfigError) as exc_info:
        await loader.load(config=_CONFIG_WITH_APPS, reference_reader=_reader(files))
    assert exc_info.value.code == "app_id_mismatch"


@pytest.mark.asyncio
async def test_missing_mcp_port_raises() -> None:
    bad_yaml = _APP_YAML.replace("  port: 3099\n", "")
    loader = WorkspaceApplicationLoader()
    files = {"apps/holaposter-ts-lite/app.runtime.yaml": bad_yaml}
    with pytest.raises(WorkspaceRuntimeConfigError) as exc_info:
        await loader.load(config=_CONFIG_WITH_APPS, reference_reader=_reader(files))
    assert exc_info.value.code == "app_mcp_port_missing"


@pytest.mark.asyncio
async def test_duplicate_app_id_raises() -> None:
    config = {
        "applications": [
            {"app_id": "holaposter-ts-lite", "config_path": "apps/holaposter-ts-lite/app.runtime.yaml"},
            {"app_id": "holaposter-ts-lite", "config_path": "apps/holaposter-ts-lite/app.runtime.yaml"},
        ]
    }
    files = {"apps/holaposter-ts-lite/app.runtime.yaml": _APP_YAML}
    loader = WorkspaceApplicationLoader()
    with pytest.raises(WorkspaceRuntimeConfigError) as exc_info:
        await loader.load(config=config, reference_reader=_reader(files))
    assert exc_info.value.code == "app_duplicate_id"
