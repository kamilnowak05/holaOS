from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sandbox_agent_runtime import hb_workflow_extensions
from sandbox_agent_runtime.memory.operations import (
    memory_get,
    memory_search,
    memory_status,
    memory_sync,
    memory_upsert,
)
from sandbox_agent_runtime.product_config import resolve_product_runtime_config


_ALLOWED_DELIVERY_CHANNELS = hb_workflow_extensions._ALLOWED_DELIVERY_CHANNELS
_ALLOWED_DELIVERY_MODES = hb_workflow_extensions._ALLOWED_DELIVERY_MODES
_cronjobs_request = hb_workflow_extensions._cronjobs_request
_cronjobs_headers = hb_workflow_extensions._cronjobs_headers
_onboarding_request = hb_workflow_extensions._onboarding_request
_onboarding_base_url = hb_workflow_extensions._onboarding_base_url
_workflow_backend = hb_workflow_extensions._workflow_backend


def _cmd_memory_search(args: argparse.Namespace) -> dict[str, Any]:
    return memory_search(
        workspace_id=args.workspace_id,
        query=args.query,
        max_results=args.max_results,
        min_score=args.min_score,
    )


def _cmd_memory_get(args: argparse.Namespace) -> dict[str, Any]:
    return memory_get(
        workspace_id=args.workspace_id,
        path=args.path,
        from_line=args.from_line,
        lines=args.lines,
    )


def _cmd_memory_upsert(args: argparse.Namespace) -> dict[str, Any]:
    return memory_upsert(
        workspace_id=args.workspace_id,
        path=args.path,
        content=args.content,
        append=bool(args.append),
    )


def _cmd_memory_status(args: argparse.Namespace) -> dict[str, Any]:
    return memory_status(workspace_id=args.workspace_id)


def _cmd_memory_sync(args: argparse.Namespace) -> dict[str, Any]:
    return memory_sync(
        workspace_id=args.workspace_id,
        reason=args.reason,
        force=bool(args.force),
    )


def _cmd_runtime_info(args: argparse.Namespace) -> dict[str, Any]:
    del args
    config = resolve_product_runtime_config(
        require_auth=False,
        require_user=False,
        require_base_url=False,
    )
    return {
        "runtime_mode": config.runtime_mode,
        "holaboss_features_enabled": config.holaboss_enabled,
        "default_harness": "opencode",
        "workflow_backend": _workflow_backend(),
        "runtime_config_path": config.config_path,
        "runtime_config_loaded": config.loaded_from_file,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runtime tools CLI")
    top = parser.add_subparsers(dest="group", required=True)

    runtime = top.add_parser("runtime", help="Runtime information")
    runtime_sub = runtime.add_subparsers(dest="action", required=True)
    runtime_sub.add_parser("info")

    hb_workflow_extensions.register_parsers(top=top)

    memory = top.add_parser("memory", help="Memory operations")
    memory_sub = memory.add_subparsers(dest="action", required=True)

    memory_search = memory_sub.add_parser("search")
    memory_search.add_argument("--workspace-id", required=True)
    memory_search.add_argument("--query", required=True)
    memory_search.add_argument("--max-results", type=int, default=6)
    memory_search.add_argument("--min-score", type=float, default=0.0)

    memory_get = memory_sub.add_parser("get")
    memory_get.add_argument("--workspace-id", required=True)
    memory_get.add_argument("--path", required=True)
    memory_get.add_argument("--from-line", type=int)
    memory_get.add_argument("--lines", type=int)

    memory_upsert = memory_sub.add_parser("upsert")
    memory_upsert.add_argument("--workspace-id", required=True)
    memory_upsert.add_argument("--path", required=True)
    memory_upsert.add_argument("--content", required=True)
    memory_upsert.add_argument("--append", action="store_true")

    memory_status = memory_sub.add_parser("status")
    memory_status.add_argument("--workspace-id", required=True)

    memory_sync = memory_sub.add_parser("sync")
    memory_sync.add_argument("--workspace-id", required=True)
    memory_sync.add_argument("--reason", default="manual")
    memory_sync.add_argument("--force", action="store_true")

    return parser


def run(argv: list[str]) -> Any:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.group == "runtime":
        if args.action == "info":
            return _cmd_runtime_info(args)
        raise RuntimeError(f"unsupported runtime action: {args.action}")

    if args.group == "memory":
        if args.action == "search":
            return _cmd_memory_search(args)
        if args.action == "get":
            return _cmd_memory_get(args)
        if args.action == "upsert":
            return _cmd_memory_upsert(args)
        if args.action == "status":
            return _cmd_memory_status(args)
        if args.action == "sync":
            return _cmd_memory_sync(args)
        raise RuntimeError(f"unsupported memory action: {args.action}")

    if args.group in {"cronjobs", "onboarding"}:
        return hb_workflow_extensions.run(args)

    raise RuntimeError(f"unsupported command group: {args.group}")


def _emit_json(payload: Any, *, stream: Any) -> None:
    stream.write(json.dumps(payload, ensure_ascii=True))
    stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    try:
        payload = run(args)
    except Exception as exc:
        _emit_json({"error": exc.__class__.__name__, "message": str(exc)}, stream=sys.stderr)
        return 1
    _emit_json(payload, stream=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
