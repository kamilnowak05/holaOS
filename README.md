# Hola Boss OSS

Holaboss OSS is the public home for the runtime code and packaging assets that power local and hosted Holaboss execution.

## Layout

- `runtime/src/`: Python source of truth for `sandbox_agent_runtime`
- `runtime/tests/`: pytest coverage for the runtime package
- `runtime/deploy/`: Dockerfiles, bootstrap scripts, entrypoints, and bundle assembly
- `docs/`: runtime boundary and packaging notes

## Development

Runtime tests live under `runtime/tests/` and are configured by `runtime/pyproject.toml`.

```bash
cd runtime
uv run pytest
```

Release and bundle workflows build from:
- `runtime/src/**`
- `runtime/pyproject.toml`
- `runtime/uv.lock`
- `runtime/deploy/**`

`runtime/deploy` packages the runtime, but it is no longer the source of truth for Python code.


## Star History

<a href="https://www.star-history.com/?repos=holaboss-ai%2Fhola-boss-oss&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=holaboss-ai/hola-boss-oss&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=holaboss-ai/hola-boss-oss&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/image?repos=holaboss-ai/hola-boss-oss&type=date&legend=top-left" />
 </picture>
</a>
