from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

MemorySource = Literal["memory"]
MemoryBackend = Literal["builtin", "qmd"]
MemoryCitationsMode = Literal["auto", "on", "off"]


@dataclass(frozen=True)
class MemorySearchResult:
    path: str
    start_line: int
    end_line: int
    score: float
    snippet: str
    source: MemorySource = "memory"
    citation: str | None = None


@dataclass(frozen=True)
class MemoryReadResult:
    text: str
    path: str


@dataclass(frozen=True)
class MemorySearchOptions:
    max_results: int | None = None
    min_score: float | None = None


@dataclass(frozen=True)
class MemorySyncOptions:
    reason: str | None = None
    force: bool = False


@dataclass(frozen=True)
class MemoryProviderStatus:
    backend: MemoryBackend
    provider: str
    model: str | None = None
    requested_provider: str | None = None
    files: int | None = None
    chunks: int | None = None
    dirty: bool | None = None
    workspace_dir: str | None = None
    db_path: str | None = None
    extra_paths: list[str] = field(default_factory=list)
    sources: list[MemorySource] = field(default_factory=lambda: ["memory"])
    fallback: dict[str, str] | None = None
    custom: dict[str, Any] = field(default_factory=dict)


class MemorySearchManager(Protocol):
    def search(self, query: str, opts: MemorySearchOptions | None = None) -> list[MemorySearchResult]: ...

    def read_file(
        self,
        *,
        rel_path: str,
        from_line: int | None = None,
        lines: int | None = None,
    ) -> MemoryReadResult: ...

    def upsert_file(self, *, rel_path: str, content: str, append: bool = False) -> MemoryReadResult: ...

    def status(self) -> MemoryProviderStatus: ...

    def sync(self, opts: MemorySyncOptions | None = None) -> None: ...

    def close(self) -> None: ...
