# Hola Boss OSS

Private staging repo for extracting the OSS runtime/distribution surface of Holaboss.

Current scope is intentionally narrow:
- `runtime/deploy/`, sourced from `hola-boss-ai/deploy/sandbox_image`
- repo-local docs and sync tooling

The desktop app and any broader backend/runtime support code are intentionally out of scope until the runtime boundary is proven standalone.

## Layout

- `runtime/`: current OSS candidate surface, starting from `deploy/`
- `docs/`: allowlist and standalone-boundary audit
- `scripts/`: sync/import helpers

## Current Finding

`deploy/sandbox_agent_runtime/*` in the OSS layout has no direct Python imports from `hola-boss-ai/src`.

That means the first OSS extraction step is:
1. keep `deploy/` intact
2. document its real packaging-time dependencies
3. only reintroduce more code if a dependency audit proves it is required

Use [docs/ALLOWLIST.md](docs/ALLOWLIST.md) as the import rule and [docs/STANDALONE_RUNTIME_AUDIT.md](docs/STANDALONE_RUNTIME_AUDIT.md) as the dependency record.
