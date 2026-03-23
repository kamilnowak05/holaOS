from __future__ import annotations

from pathlib import Path


def list_markdown_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file() and root.suffix.lower() == ".md":
        return [root]
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if path.is_file():
            files.append(path)
    return files


def relative_posix_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
