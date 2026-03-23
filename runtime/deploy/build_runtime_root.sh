#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${RUNTIME_ROOT}/.." && pwd)"
OUTPUT_ROOT="${1:-${REPO_ROOT}/out/runtime-root}"

RUNTIME_VERSION="$(awk -F' = ' '$1=="version" {gsub(/"/, "", $2); print $2; exit}' "${RUNTIME_ROOT}/pyproject.toml")"
if [ -z "${RUNTIME_VERSION}" ]; then
  echo "failed to resolve runtime version from pyproject.toml" >&2
  exit 1
fi

GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || printf 'unknown')"
BUILD_ID="${HOLABOSS_RUNTIME_BUILD_ID:-local}"
SCHEMA_VERSION="${HOLABOSS_RUNTIME_SCHEMA_VERSION:-1}"
BUILD_TIMESTAMP_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

rm -rf "${OUTPUT_ROOT}"
mkdir -p "${OUTPUT_ROOT}/app" "${OUTPUT_ROOT}/bin"

cp "${RUNTIME_ROOT}/pyproject.toml" "${OUTPUT_ROOT}/app/pyproject.toml"
cp "${RUNTIME_ROOT}/uv.lock" "${OUTPUT_ROOT}/app/uv.lock"
cp -R "${RUNTIME_ROOT}/src/sandbox_agent_runtime" "${OUTPUT_ROOT}/app/sandbox_agent_runtime"
cp -R "${SCRIPT_DIR}/bootstrap" "${OUTPUT_ROOT}/bootstrap"

cat > "${OUTPUT_ROOT}/bin/hb" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

RUNTIME_APP_ROOT="${HOLABOSS_RUNTIME_APP_ROOT:-/app}"
RUNTIME_PYTHON="${HOLABOSS_RUNTIME_PYTHON:-/opt/venv/bin/python}"
RUNTIME_SITE_PACKAGES="${HOLABOSS_RUNTIME_SITE_PACKAGES:-}"

export PYTHONPATH="${RUNTIME_APP_ROOT}${RUNTIME_SITE_PACKAGES:+:${RUNTIME_SITE_PACKAGES}}${PYTHONPATH:+:${PYTHONPATH}}"
exec "${RUNTIME_PYTHON}" -m sandbox_agent_runtime.hb_cli "$@"
EOF
chmod +x "${OUTPUT_ROOT}/bin/hb"
chmod +x "${OUTPUT_ROOT}/bootstrap/"*.sh

cat > "${OUTPUT_ROOT}/metadata.json" <<EOF
{
  "runtime_version": "${RUNTIME_VERSION}",
  "runtime_schema_version": "${SCHEMA_VERSION}",
  "git_sha": "${GIT_SHA}",
  "build_id": "${BUILD_ID}",
  "built_at_utc": "${BUILD_TIMESTAMP_UTC}",
  "source_path": "runtime/src"
}
EOF

echo "assembled runtime root at ${OUTPUT_ROOT}" >&2
