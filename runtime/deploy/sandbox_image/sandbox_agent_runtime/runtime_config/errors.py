from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WorkspaceRuntimeConfigError(Exception):
    code: str
    message: str
    path: str | None = None
    hint: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.__str__())

    def __str__(self) -> str:
        location = f" at {self.path}" if self.path else ""
        hint = f" (hint: {self.hint})" if self.hint else ""
        return f"{self.code}{location}: {self.message}{hint}"
