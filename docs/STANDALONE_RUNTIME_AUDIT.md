# Standalone Runtime Audit

This audit answers one question:

Can the OSS runtime under `runtime/src/sandbox_agent_runtime/*` stand alone without importing code from `hola-boss-ai/src`?

## Result

Yes on the Python import boundary.

Direct scan result:
- `runtime/src/sandbox_agent_runtime/*` has no direct imports whose top-level module is `api`, `core`, `services`, `config`, `shared`, `utils`, or `integrations`
- so the runtime package itself does not currently depend on `src/...` Python modules

## What It Does Depend On

The runtime package still depends on sibling runtime files for packaging and startup:

- `runtime/pyproject.toml`
- `runtime/uv.lock`
- `runtime/deploy/bootstrap/container.sh`
- `runtime/deploy/bootstrap/macos.sh`
- `runtime/deploy/bootstrap/shared.sh`
- `runtime/deploy/build_runtime_root.sh`
- `runtime/deploy/entrypoint.sh`
- `runtime/deploy/package_macos_runtime.sh`
- `runtime/deploy/Dockerfile`
- `runtime/deploy/Dockerfile.toolchain`

Those are packaging/runtime-root dependencies, not `src/...` dependencies.

## Remaining Path Assumptions

These have now been normalized in the OSS repo:

- `build_runtime_root.sh` defaults output to `runtime/out/runtime-root`
- `package_macos_runtime.sh` defaults output to `runtime/out/runtime-macos`
- `Dockerfile` now expects its build context to be the repo root and consumes:
  - `runtime/src`
  - `runtime/pyproject.toml`
  - `runtime/uv.lock`
  - `runtime/deploy`

## What Was Removed From The OSS Repo

The repo no longer treats `runtime/deploy` as the source of truth for Python code. Python source and tests now live under `runtime/src` and `runtime/tests`.

## Audit Method

Direct dependency scan:

```bash
cd /Users/jeffrey/Desktop/hola-boss-ai
python - <<'PY'
from pathlib import Path
import ast

base = Path("runtime/src/sandbox_agent_runtime")
roots = {"api", "core", "services", "config", "shared", "utils", "integrations"}

for path in sorted(base.rglob("*.py")):
    tree = ast.parse(path.read_text())
    deps = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            deps.update(name.name for name in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            deps.add(node.module)
    deps = sorted(d for d in deps if d.split(".")[0] in roots)
    if deps:
        print(path)
        for dep in deps:
            print(" ", dep)
PY
```

Observed output:
- no matches

## Next Step

Keep the runtime boundary stable:
- `runtime/src` owns Python code
- `runtime/tests` owns pytest coverage
- `runtime/deploy` owns packaging only
