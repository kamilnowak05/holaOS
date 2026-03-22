# Standalone Runtime Audit

This audit answers one question:

Can `deploy/sandbox_image/sandbox_agent_runtime/*` stand alone without importing code from `hola-boss-ai/src`?

## Result

Yes on the Python import boundary.

Direct scan result:
- `deploy/sandbox_image/sandbox_agent_runtime/*` has no direct imports whose top-level module is `api`, `core`, `services`, `config`, `shared`, `utils`, or `integrations`
- so the runtime package itself does not currently depend on `src/...` Python modules

## What It Does Depend On

The runtime package still depends on sibling files under `deploy/sandbox_image` for packaging and startup:

- `deploy/sandbox_image/pyproject.toml`
- `deploy/sandbox_image/uv.lock`
- `deploy/sandbox_image/bootstrap/container.sh`
- `deploy/sandbox_image/bootstrap/macos.sh`
- `deploy/sandbox_image/bootstrap/shared.sh`
- `deploy/sandbox_image/build_runtime_root.sh`
- `deploy/sandbox_image/entrypoint.sh`
- `deploy/sandbox_image/package_macos_runtime.sh`
- `deploy/sandbox_image/Dockerfile`
- `deploy/sandbox_image/Dockerfile.toolchain`

Those are packaging/runtime-root dependencies, not `src/...` dependencies.

## Remaining Path Assumptions

These have now been normalized in the OSS repo:

- `build_runtime_root.sh` defaults output to `runtime/out/runtime-root`
- `package_macos_runtime.sh` defaults output to `runtime/out/runtime-macos`
- `Dockerfile` now expects its build context to be the `sandbox_image` directory itself

## What Was Removed From The OSS Repo

The following broad imports were intentionally removed because they are not justified by this audit:

- `desktop/`
- `runtime/src/`
- `runtime/test/`
- `runtime/examples/`
- `runtime/scripts/`
- top-level runtime compose files and other broader repo carry-over

## Audit Method

Direct dependency scan:

```bash
cd /Users/jeffrey/Desktop/hola-boss-ai
python - <<'PY'
from pathlib import Path
import ast

base = Path("deploy/sandbox_image/sandbox_agent_runtime")
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

Make `deploy/sandbox_image` the sole imported runtime surface in `hola-boss-oss`, then separately audit whether any external release flow still requires additional non-`src` files outside that subtree.
