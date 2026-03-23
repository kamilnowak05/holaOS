# ruff: noqa: S101

from __future__ import annotations

import json

import pytest
from sandbox_agent_runtime import hb_cli, hb_workflow_extensions


def test_run_cronjobs_list_normalizes_list_payload(monkeypatch) -> None:
    def _fake_request(*, method: str, path: str = "", payload=None, params=None, allow_404: bool = False):
        del method, path, payload, params, allow_404
        return [{"id": "job-1"}, {"id": "job-2"}]

    monkeypatch.setattr(hb_workflow_extensions, "_cronjobs_request", _fake_request)

    payload = hb_cli.run(["cronjobs", "list", "--workspace-id", "workspace-1"])
    assert payload["count"] == 2
    assert len(payload["jobs"]) == 2


def test_run_memory_upsert_uses_shared_memory_operations(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_memory_upsert(*, workspace_id: str, path: str, content: str, append: bool = False) -> dict[str, str]:
        captured["workspace_id"] = workspace_id
        captured["path"] = path
        captured["content"] = content
        captured["append"] = append
        return {"path": path, "text": content}

    monkeypatch.setattr(hb_cli, "memory_upsert", _fake_memory_upsert)

    payload = hb_cli.run([
        "memory",
        "upsert",
        "--workspace-id",
        "workspace-1",
        "--path",
        "workspace/workspace-1/state.md",
        "--content",
        "hello",
    ])
    assert payload == {"path": "workspace/workspace-1/state.md", "text": "hello"}
    assert captured == {
        "workspace_id": "workspace-1",
        "path": "workspace/workspace-1/state.md",
        "content": "hello",
        "append": False,
    }


def test_run_memory_status_returns_status_dict(monkeypatch) -> None:
    status_payload = {"backend": "builtin", "provider": "filesystem", "workspace_dir": "/workspace/test"}
    monkeypatch.setattr(hb_cli, "memory_status", lambda *, workspace_id: status_payload)

    payload = hb_cli.run([
        "memory",
        "status",
        "--workspace-id",
        "workspace-1",
    ])
    assert payload == status_payload


def test_main_returns_json_error_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(hb_cli, "run", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    stderr: list[str] = []
    monkeypatch.setattr(hb_cli, "_emit_json", lambda payload, stream: stderr.append(str(payload)))

    assert hb_cli.main(["cronjobs", "list", "--workspace-id", "workspace-1"]) == 1
    assert "boom" in stderr[0]


def test_delivery_channels_match_api_contract() -> None:
    assert frozenset({"system_notification", "session_run"}) == hb_cli._ALLOWED_DELIVERY_CHANNELS


def test_run_cronjobs_create_rejects_legacy_delivery_channel() -> None:
    with pytest.raises(SystemExit):
        hb_cli.run([
            "cronjobs",
            "create",
            "--workspace-id",
            "workspace-1",
            "--cron",
            "0 * * * *",
            "--description",
            "Drink water",
            "--delivery-channel",
            "proactive_event",
        ])


def test_run_onboarding_status_uses_onboarding_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_onboarding_request(*, method: str, path: str, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"workspace_id": "workspace-1", "onboarding_status": "pending"}

    monkeypatch.setattr(hb_workflow_extensions, "_onboarding_request", _fake_onboarding_request)

    payload = hb_cli.run(["onboarding", "status", "--workspace-id", "workspace-1"])
    assert payload["onboarding_status"] == "pending"
    assert captured == {
        "method": "GET",
        "path": "/workspace-1/status",
        "payload": None,
    }


def test_run_onboarding_request_complete_uses_onboarding_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_onboarding_request(*, method: str, path: str, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"workspace_id": "workspace-1", "onboarding_status": "awaiting_confirmation"}

    monkeypatch.setattr(hb_workflow_extensions, "_onboarding_request", _fake_onboarding_request)

    payload = hb_cli.run([
        "onboarding",
        "request-complete",
        "--workspace-id",
        "workspace-1",
        "--summary",
        "Captured goals and constraints",
    ])
    assert payload["onboarding_status"] == "awaiting_confirmation"
    assert captured == {
        "method": "POST",
        "path": "/workspace-1/request-complete",
        "payload": {
            "summary": "Captured goals and constraints",
            "requested_by": "workspace_agent",
        },
    }


def test_runtime_still_supports_cronjobs_and_onboarding_groups(monkeypatch) -> None:
    monkeypatch.setattr(
        hb_workflow_extensions,
        "_cronjobs_request",
        lambda **_: [],
    )
    monkeypatch.setattr(
        hb_workflow_extensions,
        "_onboarding_request",
        lambda **_: {"workspace_id": "workspace-1", "onboarding_status": "pending"},
    )

    cronjobs_payload = hb_cli.run(["cronjobs", "list", "--workspace-id", "workspace-1"])
    onboarding_payload = hb_cli.run(["onboarding", "status", "--workspace-id", "workspace-1"])

    assert cronjobs_payload == {"jobs": [], "count": 0}
    assert onboarding_payload["workspace_id"] == "workspace-1"
    assert onboarding_payload["onboarding_status"] == "pending"


def test_oss_flavor_still_supports_memory_group(monkeypatch) -> None:
    monkeypatch.setattr(hb_cli, "memory_status", lambda *, workspace_id: {"workspace_id": workspace_id})

    payload = hb_cli.run(["memory", "status", "--workspace-id", "workspace-1"])

    assert payload == {"workspace_id": "workspace-1"}


def test_runtime_info_reports_runtime_mode(monkeypatch) -> None:
    payload = hb_cli.run(["runtime", "info"])

    assert payload == {
        "runtime_mode": "oss",
        "holaboss_features_enabled": False,
        "default_harness": "opencode",
        "workflow_backend": "remote_api",
        "runtime_config_path": "/holaboss/state/runtime-config.json",
        "runtime_config_loaded": False,
    }


def test_cronjobs_headers_accept_product_auth_aliases(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "runtime-config.json"
    config_path.write_text(
        json.dumps({"holaboss": {"sandbox_id": "sandbox-1"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOLABOSS_RUNTIME_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HOLABOSS_SANDBOX_AUTH_TOKEN", "token-1")
    monkeypatch.setenv("HOLABOSS_USER_ID", "user-1")

    headers = hb_workflow_extensions._cronjobs_headers()

    assert headers == {
        "X-API-Key": "token-1",
        "X-Holaboss-User-Id": "user-1",
        "X-Holaboss-Sandbox-Id": "sandbox-1",
    }


def test_onboarding_base_url_accepts_product_base_url_alias(monkeypatch) -> None:
    monkeypatch.setenv("HOLABOSS_MODEL_PROXY_BASE_URL", "https://runtime.example/api/v1/model-proxy")

    assert (
        hb_workflow_extensions._onboarding_base_url() == "https://runtime.example/api/v1/sandbox/onboarding/workspaces"
    )


def test_local_sqlite_backend_alias_still_uses_local_cronjobs_requests(monkeypatch) -> None:
    monkeypatch.setenv("HOLABOSS_RUNTIME_WORKFLOW_BACKEND", "local_sqlite")
    captured: dict[str, object] = {}

    def _fake_request(*, method: str, path: str = "", payload=None, params=None, allow_404: bool = False):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        captured["params"] = params
        captured["allow_404"] = allow_404
        return []

    monkeypatch.setattr(hb_workflow_extensions, "_cronjobs_request", _fake_request)

    payload = hb_cli.run(["cronjobs", "list", "--workspace-id", "workspace-1"])

    assert payload == {"jobs": [], "count": 0}
    assert captured["method"] == "GET"
    assert captured["path"] == ""
    assert captured["params"] == {
        "workspace_id": "workspace-1",
        "enabled_only": False,
    }


def test_local_sqlite_backend_alias_still_uses_remote_onboarding_requests(monkeypatch) -> None:
    monkeypatch.setenv("HOLABOSS_RUNTIME_WORKFLOW_BACKEND", "local_sqlite")
    captured: dict[str, object] = {}

    def _fake_onboarding_request(*, method: str, path: str, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"workspace_id": "workspace-1", "onboarding_status": "awaiting_confirmation"}

    monkeypatch.setattr(hb_workflow_extensions, "_onboarding_request", _fake_onboarding_request)

    payload = hb_cli.run(["onboarding", "status", "--workspace-id", "workspace-1"])

    assert payload["onboarding_status"] == "awaiting_confirmation"
    assert captured == {
        "method": "GET",
        "path": "/workspace-1/status",
        "payload": None,
    }
