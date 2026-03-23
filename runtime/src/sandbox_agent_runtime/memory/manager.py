from __future__ import annotations

from pathlib import Path

from sandbox_agent_runtime.memory.fs_utils import list_markdown_files, relative_posix_path
from sandbox_agent_runtime.memory.internal import (
    is_memory_path,
    normalize_rel_path,
    read_line_window,
    resolve_memory_root_dir,
    score_text,
    snippet_for_match,
    workspace_scope_prefix,
)
from sandbox_agent_runtime.memory.types import (
    MemoryProviderStatus,
    MemoryReadResult,
    MemorySearchOptions,
    MemorySearchResult,
    MemorySyncOptions,
)


class BuiltinMemoryManager:
    def __init__(
        self,
        *,
        workspace_dir: Path,
        workspace_id: str,
        requested_provider: str | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        self._workspace_dir = workspace_dir.resolve()
        self._workspace_scope_prefix = workspace_scope_prefix(workspace_id=workspace_id)
        self._memory_root_dir = resolve_memory_root_dir(workspace_dir=self._workspace_dir)
        self._requested_provider = requested_provider
        self._fallback_reason = fallback_reason

    def search(self, query: str, opts: MemorySearchOptions | None = None) -> list[MemorySearchResult]:
        options = opts or MemorySearchOptions()
        cleaned_query = query.strip()
        if not cleaned_query:
            return []
        max_results = options.max_results if options.max_results and options.max_results > 0 else 6
        min_score = options.min_score if options.min_score is not None else 0.0

        results: list[MemorySearchResult] = []
        for path in self._memory_files():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            score = score_text(cleaned_query, text)
            if score < min_score:
                continue
            snippet, start_line, end_line = snippet_for_match(text, cleaned_query)
            rel_path = relative_posix_path(self._memory_root_dir, path)
            results.append(
                MemorySearchResult(
                    path=rel_path,
                    start_line=start_line,
                    end_line=end_line,
                    score=score,
                    snippet=snippet,
                )
            )

        ranked = sorted(results, key=lambda item: (-item.score, item.path, item.start_line))
        return ranked[:max_results]

    def read_file(
        self,
        *,
        rel_path: str,
        from_line: int | None = None,
        lines: int | None = None,
    ) -> MemoryReadResult:
        normalized = normalize_rel_path(rel_path)
        if not is_memory_path(normalized, workspace_id=self.workspace_id):
            raise ValueError(
                "allowed memory paths: workspace/<workspace_id>/* and user scopes like preference/*",
            )
        target = (self._memory_root_dir / normalized).resolve()
        if self._memory_root_dir not in target.parents and target != self._memory_root_dir:
            raise ValueError("path escapes memory root")
        if not target.is_file():
            raise FileNotFoundError(normalized)
        text = target.read_text(encoding="utf-8")
        return MemoryReadResult(path=normalized, text=read_line_window(text, from_line=from_line, lines=lines))

    def upsert_file(self, *, rel_path: str, content: str, append: bool = False) -> MemoryReadResult:
        normalized = normalize_rel_path(rel_path)
        if not is_memory_path(normalized, workspace_id=self.workspace_id):
            raise ValueError(
                "allowed memory paths: workspace/<workspace_id>/* and user scopes like preference/*",
            )
        target = (self._memory_root_dir / normalized).resolve()
        if self._memory_root_dir not in target.parents and target != self._memory_root_dir:
            raise ValueError("path escapes memory root")
        target.parent.mkdir(parents=True, exist_ok=True)

        if append and target.exists():
            existing = target.read_text(encoding="utf-8")
            prefix = "\n" if existing and not existing.endswith("\n") else ""
            target.write_text(f"{existing}{prefix}{content}", encoding="utf-8")
        elif append and not target.exists():
            target.write_text(content, encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")

        return MemoryReadResult(path=normalized, text=target.read_text(encoding="utf-8"))

    def status(self) -> MemoryProviderStatus:
        files = self._memory_files()
        fallback = None
        if self._requested_provider and self._requested_provider != "builtin" and self._fallback_reason:
            fallback = {
                "from": self._requested_provider,
                "reason": self._fallback_reason,
            }
        return MemoryProviderStatus(
            backend="builtin",
            provider="filesystem",
            requested_provider=self._requested_provider,
            files=len(files),
            chunks=len(files),
            workspace_dir=str(self._workspace_dir),
            fallback=fallback,
            custom={
                "memory_root_dir": str(self._memory_root_dir),
                "workspace_scope": self._workspace_scope_prefix.rstrip("/"),
            },
        )

    def sync(self, opts: MemorySyncOptions | None = None) -> None:
        del opts

    def close(self) -> None:
        return None

    @property
    def workspace_id(self) -> str:
        return self._workspace_scope_prefix.split("/", 2)[1]

    @property
    def memory_root_dir(self) -> Path:
        return self._memory_root_dir

    def _memory_files(self) -> list[Path]:
        files: list[Path] = []
        workspace_scope_dir = self._memory_root_dir / self._workspace_scope_prefix.rstrip("/")
        files.extend(list_markdown_files(workspace_scope_dir))

        if self._memory_root_dir.is_dir():
            for child in sorted(self._memory_root_dir.iterdir()):
                if not child.is_dir() or child.name == "workspace":
                    continue
                files.extend(list_markdown_files(child))
        return files
