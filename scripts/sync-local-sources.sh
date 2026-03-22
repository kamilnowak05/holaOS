#!/usr/bin/env bash

set -euo pipefail

OSS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AI_SRC="${AI_SRC:-/Users/jeffrey/Desktop/hola-boss-ai}"
RUNTIME_DEST="$OSS_ROOT/runtime"

AI_PATHS=(
  deploy/sandbox_image
)

require_git_repo() {
  local path="$1"
  git -C "$path" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

sync_tree_from_git() {
  local src="$1"
  local dest="$2"
  shift 2

  rm -rf "$dest"
  mkdir -p "$dest"

  if [ "$#" -eq 0 ]; then
    git -C "$src" archive --format=tar HEAD | tar -x -C "$dest"
    return
  fi

  git -C "$src" archive --format=tar HEAD "$@" | tar -x -C "$dest"
}

main() {
  require_git_repo "$AI_SRC" || {
    echo "ai source is not a git repo: $AI_SRC" >&2
    exit 1
  }

  rm -rf "$RUNTIME_DEST"
  mkdir -p "$RUNTIME_DEST"
  sync_tree_from_git "$AI_SRC" "$RUNTIME_DEST" "${AI_PATHS[@]}"

  echo "synced runtime/deploy/sandbox_image -> $RUNTIME_DEST/deploy/sandbox_image"
}

main "$@"
