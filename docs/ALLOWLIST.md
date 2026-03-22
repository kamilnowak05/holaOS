# OSS Allowlist

The repo is intentionally in a reduction phase. The immediate goal is to make the shared runtime package standalone before any broader OSS import.

## Allowed Import Source

Only import this path from `hola-boss-ai`:

- `deploy/sandbox_image/`

It should land in this repo as:

- `runtime/deploy/`

## Not Allowed Right Now

Do not import any of the following until a dependency audit proves they are required:

- any path under `hola-boss-ai/src/`
- any path under `hola-boss-ai/test/`
- `hola-boss-ai/examples/`
- `hola-boss-ai/scripts/`
- top-level runtime compose files or repo-level packaging files outside the imported `deploy/sandbox_image` source boundary
- any files from `hola-boss-desktop`

## Rule For Expanding The Boundary

If a future import is needed:

1. prove the dependency with code or packaging analysis
2. document it in `docs/STANDALONE_RUNTIME_AUDIT.md`
3. then expand this allowlist

## Release Rule

`hola-boss-oss` should only widen from the standalone runtime boundary after that boundary is clean and reproducible.
