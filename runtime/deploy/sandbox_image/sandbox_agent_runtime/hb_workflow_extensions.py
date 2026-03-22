from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from sandbox_agent_runtime.product_config import resolve_product_runtime_config

_CRONJOBS_SERVICE_URL_ENV = "CRONJOBS_SERVICE_URL"
_SANDBOX_AGENT_BASE_URL_ENV = "SANDBOX_AGENT_BASE_URL"
_WORKFLOW_BACKEND_ENV = "HOLABOSS_RUNTIME_WORKFLOW_BACKEND"
_WORKFLOW_BACKEND_REMOTE_API = "remote_api"
_WORKFLOW_BACKEND_LOCAL_SQLITE = "local_sqlite"
_ALLOWED_DELIVERY_MODES = frozenset({"none", "announce"})
_ALLOWED_DELIVERY_CHANNELS = frozenset({"system_notification", "session_run"})


def _parse_bool(value: str) -> bool:
    token = value.strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected boolean value (true|false)")


def _parse_json_object(raw: str, *, field_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON object") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{field_name} must be JSON object")
    return payload


def _normalize_delivery(*, channel: str, mode: str = "announce", to: str | None = None) -> dict[str, Any]:
    normalized_mode = str(mode).strip()
    normalized_channel = str(channel).strip()
    if normalized_mode not in _ALLOWED_DELIVERY_MODES:
        raise ValueError(f"delivery mode must be one of {sorted(_ALLOWED_DELIVERY_MODES)}")
    if normalized_channel not in _ALLOWED_DELIVERY_CHANNELS:
        raise ValueError(f"delivery channel must be one of {sorted(_ALLOWED_DELIVERY_CHANNELS)}")
    return {
        "mode": normalized_mode,
        "channel": normalized_channel,
        "to": to,
    }


def _cronjobs_base_url() -> str:
    base_url = (os.getenv(_SANDBOX_AGENT_BASE_URL_ENV) or "http://127.0.0.1:8080").strip().rstrip("/")
    if not base_url:
        raise RuntimeError(f"{_SANDBOX_AGENT_BASE_URL_ENV} is required")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"{_SANDBOX_AGENT_BASE_URL_ENV} must be an absolute http(s) URL")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"{_SANDBOX_AGENT_BASE_URL_ENV} must not include query or fragment")
    if base_url.endswith("/api/v1/cronjobs"):
        return base_url
    return f"{base_url}/api/v1/cronjobs"


def _cronjobs_headers() -> dict[str, str]:
    return resolve_product_runtime_config(require_base_url=False).headers


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
    return str(payload)


def _workflow_backend() -> str:
    raw = (os.getenv(_WORKFLOW_BACKEND_ENV) or _WORKFLOW_BACKEND_REMOTE_API).strip().lower()
    # Keep accepting the legacy local_sqlite token as a compatibility alias.
    if raw in {_WORKFLOW_BACKEND_REMOTE_API, _WORKFLOW_BACKEND_LOCAL_SQLITE}:
        return raw
    return _WORKFLOW_BACKEND_REMOTE_API


def _onboarding_base_url() -> str:
    config = resolve_product_runtime_config(require_auth=False, require_user=False)
    model_proxy_base_url = config.model_proxy_base_url
    suffix = "/api/v1/model-proxy"
    if not model_proxy_base_url.endswith(suffix):
        raise RuntimeError(f"HOLABOSS_MODEL_PROXY_BASE_URL must end with {suffix}")
    runtime_base_url = model_proxy_base_url.removesuffix(suffix)
    return f"{runtime_base_url}/api/v1/sandbox/onboarding/workspaces"


def _cronjobs_request(
    *,
    method: str,
    path: str = "",
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    allow_404: bool = False,
) -> Any:
    url = f"{_cronjobs_base_url()}{path}"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method=method,
                url=url,
                headers={},
                json=payload,
                params=params,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"cronjobs API request failed: {exc}") from exc

    if allow_404 and response.status_code == 404:
        return None
    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise RuntimeError(f"cronjobs API error status={response.status_code} detail={detail}")
    if response.status_code == 204:
        return {"success": True}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("cronjobs API returned non-JSON response") from exc


def _onboarding_request(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = f"{_onboarding_base_url()}{path}"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method=method,
                url=url,
                headers=_cronjobs_headers(),
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"onboarding API request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise RuntimeError(f"onboarding API error status={response.status_code} detail={detail}")
    if response.status_code == 204:
        return {"success": True}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("onboarding API returned non-JSON response") from exc


def _cmd_cronjobs_create(args: argparse.Namespace) -> dict[str, Any]:
    metadata = _parse_json_object(args.metadata_json, field_name="metadata_json")
    config = resolve_product_runtime_config(require_auth=False, require_base_url=False, require_user=False)
    if config.user_id and not isinstance(metadata.get("holaboss_user_id"), str):
        metadata["holaboss_user_id"] = config.user_id
    payload = {
        "workspace_id": args.workspace_id,
        "initiated_by": args.initiated_by,
        "cron": args.cron,
        "description": args.description,
        "enabled": _parse_bool(args.enabled),
        "delivery": _normalize_delivery(
            channel=args.delivery_channel,
            mode=args.delivery_mode,
            to=args.delivery_to,
        ),
        "metadata": metadata,
    }
    created = _cronjobs_request(method="POST", payload=payload)
    if isinstance(created, dict):
        return created
    return {"result": created}


def _cmd_cronjobs_list(args: argparse.Namespace) -> dict[str, Any]:
    listed = _cronjobs_request(
        method="GET",
        params={
            "workspace_id": args.workspace_id,
            "enabled_only": bool(args.enabled_only),
        },
    )
    if isinstance(listed, dict):
        return listed
    if isinstance(listed, list):
        return {"jobs": listed, "count": len(listed)}
    return {"jobs": [], "count": 0}


def _cmd_cronjobs_get(args: argparse.Namespace) -> dict[str, Any] | None:
    result = _cronjobs_request(method="GET", path=f"/{args.job_id}", allow_404=True)
    if result is None:
        return None
    if not isinstance(result, dict):
        return {"result": result}
    if args.workspace_id and result.get("workspace_id") != args.workspace_id:
        raise RuntimeError("requested cronjob does not belong to this workspace")
    return result


def _cmd_cronjobs_update(args: argparse.Namespace) -> dict[str, Any]:
    existing = _cronjobs_request(method="GET", path=f"/{args.job_id}", allow_404=True)
    if existing is None:
        raise RuntimeError("cronjob not found")
    if not isinstance(existing, dict):
        raise TypeError("invalid cronjob response while loading existing job")
    if args.workspace_id and existing.get("workspace_id") != args.workspace_id:
        raise RuntimeError("requested cronjob does not belong to this workspace")

    existing_delivery = existing.get("delivery")
    if not isinstance(existing_delivery, dict):
        existing_delivery = {}
    delivery = _normalize_delivery(
        channel=args.delivery_channel or str(existing_delivery.get("channel") or "session_run"),
        mode=args.delivery_mode or str(existing_delivery.get("mode") or "announce"),
        to=args.delivery_to if args.delivery_to is not None else existing_delivery.get("to"),
    )

    update_payload: dict[str, Any] = {"delivery": delivery}
    if args.cron is not None:
        update_payload["cron"] = args.cron
    if args.description is not None:
        update_payload["description"] = args.description
    if args.enabled is not None:
        update_payload["enabled"] = _parse_bool(args.enabled)
    if args.metadata_json is not None:
        update_payload["metadata"] = _parse_json_object(args.metadata_json, field_name="metadata_json")

    updated = _cronjobs_request(method="PATCH", path=f"/{args.job_id}", payload=update_payload)
    if isinstance(updated, dict):
        return updated
    return {"result": updated}


def _cmd_cronjobs_delete(args: argparse.Namespace) -> dict[str, Any]:
    existing = _cronjobs_request(method="GET", path=f"/{args.job_id}", allow_404=True)
    if existing is None:
        return {"success": False}
    if isinstance(existing, dict) and args.workspace_id and existing.get("workspace_id") != args.workspace_id:
        raise RuntimeError("requested cronjob does not belong to this workspace")
    deleted = _cronjobs_request(method="DELETE", path=f"/{args.job_id}")
    if isinstance(deleted, dict):
        return deleted
    return {"success": bool(deleted)}


def _cmd_onboarding_status(args: argparse.Namespace) -> dict[str, Any]:
    payload = _onboarding_request(
        method="GET",
        path=f"/{args.workspace_id}/status",
    )
    if isinstance(payload, dict):
        return payload
    return {"result": payload}


def _cmd_onboarding_request_complete(args: argparse.Namespace) -> dict[str, Any]:
    requested_by = str(args.requested_by).strip() or "workspace_agent"
    payload = _onboarding_request(
        method="POST",
        path=f"/{args.workspace_id}/request-complete",
        payload={
            "summary": args.summary,
            "requested_by": requested_by,
        },
    )
    if isinstance(payload, dict):
        return payload
    return {"result": payload}


def register_parsers(*, top: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cronjobs = top.add_parser("cronjobs", help="Cronjob operations")
    cronjobs_sub = cronjobs.add_subparsers(dest="action", required=True)

    cronjobs_create = cronjobs_sub.add_parser("create")
    cronjobs_create.add_argument("--workspace-id", required=True)
    cronjobs_create.add_argument("--initiated-by", default="workspace_agent")
    cronjobs_create.add_argument("--cron", required=True)
    cronjobs_create.add_argument("--description", required=True)
    cronjobs_create.add_argument("--enabled", default="true")
    cronjobs_create.add_argument(
        "--delivery-channel", default="session_run", choices=sorted(_ALLOWED_DELIVERY_CHANNELS)
    )
    cronjobs_create.add_argument("--delivery-mode", default="announce", choices=sorted(_ALLOWED_DELIVERY_MODES))
    cronjobs_create.add_argument("--delivery-to")
    cronjobs_create.add_argument("--metadata-json", default="{}")

    cronjobs_list = cronjobs_sub.add_parser("list")
    cronjobs_list.add_argument("--workspace-id", required=True)
    cronjobs_list.add_argument("--enabled-only", action="store_true")

    cronjobs_get = cronjobs_sub.add_parser("get")
    cronjobs_get.add_argument("--job-id", required=True)
    cronjobs_get.add_argument("--workspace-id")

    cronjobs_update = cronjobs_sub.add_parser("update")
    cronjobs_update.add_argument("--job-id", required=True)
    cronjobs_update.add_argument("--workspace-id")
    cronjobs_update.add_argument("--cron")
    cronjobs_update.add_argument("--description")
    cronjobs_update.add_argument("--enabled")
    cronjobs_update.add_argument("--delivery-channel", choices=sorted(_ALLOWED_DELIVERY_CHANNELS))
    cronjobs_update.add_argument("--delivery-mode", choices=sorted(_ALLOWED_DELIVERY_MODES))
    cronjobs_update.add_argument("--delivery-to")
    cronjobs_update.add_argument("--metadata-json")

    cronjobs_delete = cronjobs_sub.add_parser("delete")
    cronjobs_delete.add_argument("--job-id", required=True)
    cronjobs_delete.add_argument("--workspace-id")

    onboarding = top.add_parser("onboarding", help="Onboarding operations")
    onboarding_sub = onboarding.add_subparsers(dest="action", required=True)

    onboarding_status = onboarding_sub.add_parser("status")
    onboarding_status.add_argument("--workspace-id", required=True)

    onboarding_request_complete = onboarding_sub.add_parser("request-complete")
    onboarding_request_complete.add_argument("--workspace-id", required=True)
    onboarding_request_complete.add_argument("--summary", required=True)
    onboarding_request_complete.add_argument("--requested-by", default="workspace_agent")


def run(args: argparse.Namespace) -> Any:
    if args.group == "cronjobs":
        if args.action == "create":
            return _cmd_cronjobs_create(args)
        if args.action == "list":
            return _cmd_cronjobs_list(args)
        if args.action == "get":
            return _cmd_cronjobs_get(args)
        if args.action == "update":
            return _cmd_cronjobs_update(args)
        if args.action == "delete":
            return _cmd_cronjobs_delete(args)
        raise RuntimeError(f"unsupported cronjobs action: {args.action}")

    if args.group == "onboarding":
        if args.action == "status":
            return _cmd_onboarding_status(args)
        if args.action == "request-complete":
            return _cmd_onboarding_request_complete(args)
        raise RuntimeError(f"unsupported onboarding action: {args.action}")

    raise RuntimeError(f"unsupported product command group: {args.group}")
