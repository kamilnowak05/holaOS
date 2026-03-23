# OSS Runtime Boundary

The runtime repo is now organized around one Python project and one packaging surface:

- `runtime/src/`: runtime source code
- `runtime/tests/`: runtime tests
- `runtime/deploy/`: packaging and bootstrap assets

## Allowed Runtime Ownership

These paths are owned directly by `hola-boss-oss`:

- `runtime/src/**`
- `runtime/tests/**`
- `runtime/deploy/**`
- `runtime/pyproject.toml`
- `runtime/uv.lock`

## Not Allowed

Do not reintroduce private backend ownership into this repo:

- any path under `hola-boss-ai/src/`
- any path under `hola-boss-ai/test/`
- `hola-boss-ai/examples/`
- `hola-boss-ai/scripts/`
- any files from `hola-boss-desktop`

## Rule For Expanding The Boundary

If a future import is needed:

1. prove the dependency with code or packaging analysis
2. document it in `docs/STANDALONE_RUNTIME_AUDIT.md`
3. then expand this boundary deliberately
