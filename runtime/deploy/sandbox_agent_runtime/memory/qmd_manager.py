from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sandbox_agent_runtime.memory.backend_config import ResolvedQmdConfig
from sandbox_agent_runtime.memory.internal import is_memory_path, normalize_rel_path
from sandbox_agent_runtime.memory.manager import BuiltinMemoryManager
from sandbox_agent_runtime.memory.types import (
    MemoryProviderStatus,
    MemoryReadResult,
    MemorySearchOptions,
    MemorySearchResult,
    MemorySyncOptions,
)


class QmdMemoryManager:
    def __init__(self, *, workspace_dir: Path, qmd: ResolvedQmdConfig) -> None:
        self._workspace_dir = workspace_dir.resolve()
        self._qmd = qmd
        self._builtin = BuiltinMemoryManager(workspace_dir=self._workspace_dir, workspace_id=self._qmd.workspace_id)
        self._collections_initialized = False

    @classmethod
    def create(cls, *, workspace_dir: Path, qmd: ResolvedQmdConfig) -> QmdMemoryManager:
        command = qmd.command.split()[0]
        if shutil.which(command) is None:
            raise RuntimeError(f"qmd command not found: {command}")
        manager = cls(workspace_dir=workspace_dir, qmd=qmd)
        manager.sync(MemorySyncOptions(reason="boot", force=True))
        return manager

    def search(self, query: str, opts: MemorySearchOptions | None = None) -> list[MemorySearchResult]:
        options = opts or MemorySearchOptions()
        cleaned = query.strip()
        if not cleaned:
            return []

        max_results = options.max_results if options.max_results and options.max_results > 0 else self._qmd.max_results
        qmd_fetch_limit = min(max_results * 10, 100)
        command = [
            *self._command_base(),
            self._qmd.search_mode,
            cleaned,
            "--json",
            "-n",
            str(max(1, qmd_fetch_limit)),
        ]
        min_score = options.min_score
        if min_score is not None:
            command.extend(["--min-score", str(min_score)])

        payload = self._run_json(command=command, timeout_ms=self._qmd.timeout_ms)
        raw_results: list[dict[str, Any]]
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            raw_results = [item for item in payload["results"] if isinstance(item, dict)]
        elif isinstance(payload, list):
            raw_results = [item for item in payload if isinstance(item, dict)]
        else:
            raw_results = []

        parsed: list[MemorySearchResult] = []
        fallback_min_score = min_score if min_score is not None else float("-inf")
        for item in raw_results:
            rel_path = self._resolve_result_path(item)
            if rel_path is None or not is_memory_path(rel_path, workspace_id=self._qmd.workspace_id):
                continue
            score = _coerce_float(item.get("score"), default=0.0)
            if score < fallback_min_score:
                continue
            start_line = _coerce_int(
                item.get("start_line")
                or item.get("startLine")
                or item.get("line")
                or item.get("line_start")
                or item.get("lineStart"),
                default=1,
            )
            end_line = _coerce_int(
                item.get("end_line") or item.get("endLine") or item.get("line_end") or item.get("lineEnd"),
                default=start_line,
            )
            snippet_raw = item.get("snippet") or item.get("text") or item.get("content")
            snippet = str(snippet_raw).strip() if isinstance(snippet_raw, str) else ""
            if not snippet:
                try:
                    snippet = self._builtin.read_file(rel_path=rel_path, from_line=start_line, lines=5).text
                except Exception:
                    snippet = ""
            if len(snippet) > self._qmd.max_snippet_chars:
                snippet = snippet[: self._qmd.max_snippet_chars].rstrip()
            parsed.append(
                MemorySearchResult(
                    path=rel_path,
                    start_line=max(1, start_line),
                    end_line=max(max(1, start_line), end_line),
                    score=score,
                    snippet=snippet,
                )
            )

        ranked = sorted(parsed, key=lambda entry: (-entry.score, entry.path, entry.start_line))
        return ranked[:max_results]

    def read_file(
        self,
        *,
        rel_path: str,
        from_line: int | None = None,
        lines: int | None = None,
    ) -> MemoryReadResult:
        return self._builtin.read_file(rel_path=rel_path, from_line=from_line, lines=lines)

    def upsert_file(self, *, rel_path: str, content: str, append: bool = False) -> MemoryReadResult:
        updated = self._builtin.upsert_file(rel_path=rel_path, content=content, append=append)
        self.sync(MemorySyncOptions(reason="upsert", force=False))
        return updated

    def status(self) -> MemoryProviderStatus:
        builtin_status = self._builtin.status()
        return MemoryProviderStatus(
            backend="qmd",
            provider="qmd",
            model=self._qmd.search_mode,
            requested_provider="qmd",
            files=builtin_status.files,
            chunks=builtin_status.chunks,
            workspace_dir=str(self._workspace_dir),
            db_path=self._qmd.index_name,
            custom={
                "search_mode": self._qmd.search_mode,
                "command": self._qmd.command,
                "memory_root_dir": self._qmd.memory_root_dir,
            },
        )

    def sync(self, opts: MemorySyncOptions | None = None) -> None:
        options = opts or MemorySyncOptions()
        self._ensure_collections(force=options.force)
        self._run(command=[*self._command_base(), "update"], timeout_ms=self._qmd.timeout_ms)

    def close(self) -> None:
        return None

    def _command_base(self) -> list[str]:
        command_parts = self._qmd.command.split()
        return [*command_parts, "--index", self._qmd.index_name]

    def _ensure_collections(self, *, force: bool) -> None:
        if self._collections_initialized and not force:
            return
        for collection in self._qmd.collections:
            target = Path(collection.path)
            if not target.exists():
                continue
            try:
                self._run(
                    command=[
                        *self._command_base(),
                        "collection",
                        "add",
                        collection.path,
                        "--name",
                        collection.name,
                    ],
                    timeout_ms=self._qmd.timeout_ms,
                    tolerate_exists=True,
                )
            except RuntimeError as exc:
                if "already exists" in str(exc).lower():
                    continue
                raise
        self._collections_initialized = True

    def _run_json(self, *, command: list[str], timeout_ms: int) -> Any:
        output = self._run(command=command, timeout_ms=timeout_ms)
        if not output.strip():
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid qmd JSON output: {exc}") from exc

    def _run(self, *, command: list[str], timeout_ms: int, tolerate_exists: bool = False) -> str:
        timeout_seconds = max(0.25, timeout_ms / 1000.0)
        try:
            completed = subprocess.run(  # noqa: S603 - command is controlled via runtime memory config
                command,
                cwd=str(self._workspace_dir),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"qmd command timed out: {' '.join(command)}") from exc
        except OSError as exc:
            raise RuntimeError(f"failed to run qmd command: {exc}") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            reason = stderr or stdout or f"exit={completed.returncode}"
            if tolerate_exists and "already exists" in reason.lower():
                return completed.stdout or ""
            raise RuntimeError(f"qmd command failed ({' '.join(command)}): {reason[:500]}")
        return completed.stdout or ""

    def _resolve_result_path(self, item: dict[str, Any]) -> str | None:
        raw = (
            item.get("path")
            or item.get("relative_path")
            or item.get("rel_path")
            or item.get("file")
            or item.get("doc")
            or item.get("filepath")
        )
        if not isinstance(raw, str) or not raw.strip():
            return None
        token = raw.strip()
        if token.startswith("qmd://"):
            scoped = token[len("qmd://") :]
            collection_split = scoped.split("/", 1)
            if len(collection_split) != 2:
                return None
            token = collection_split[1]
        if token.startswith("#"):
            return None
        path_obj = Path(token)
        if path_obj.is_absolute():
            resolved = path_obj.resolve()
            memory_root_dir = self._builtin.memory_root_dir
            if memory_root_dir not in resolved.parents and resolved != memory_root_dir:
                return None
            return resolved.relative_to(memory_root_dir).as_posix()
        try:
            normalized = normalize_rel_path(token)
        except ValueError:
            return None
        return normalized


def _coerce_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _coerce_float(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default
