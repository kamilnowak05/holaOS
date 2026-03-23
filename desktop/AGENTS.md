# Repository Guidelines

## Project Overview
Holaboss AI is a multi-agent service platform built with Python, leveraging advanced AI capabilities for intelligent automation and task management. The system uses a distributed microservices architecture with FastAPI-based services.

## Project Structure & Module Organization
Source lives under `src/` with domain folders (`api`, `core`, `services`, `integrations`, `shared`, `utils`). Configuration schemas and runtime settings sit in `src/config`, while reusable infra (Supabase SQL, Edge Functions) is under `supabase/`. Provisioning scripts, docker assets, and telemetry configs live in the top level (`provisioning/`, `docker-compose.yml`, `loki-local-config.yaml`). Centralized tests live in the root-level `test/` directory; mirror the source tree beneath it (e.g., `test/services/hola_canvas/...`) when adding coverage.

## Documentation Responsibilities
- `README.md`: operator/deployment runbook (environment setup, Supabase setup, local deployment script, health checks, workspace CLI flow).
- `AGENTS.md`: contributor and coding-agent standards (build/test gates, coding/testing style, logging, commit/PR conventions).
- Avoid duplicating deployment instructions here; link back to `README.md` when runtime operations are needed.

## Build, Test & Development Commands
Use `make install` to bootstrap the `uv` environment, install dependencies, and register pre-commit hooks. Do not use `poetry` in this repo. A shared `.env` file lives at the repo root; when working in a git worktree, create a symlink at `.env` pointing to the root `.env` so `pydantic-settings` can load it before running `uv run pytest` or other services. `make check` chains dependency locking, linting, mypy, deptry, and pre-commit; run it before every push. `uv run coverage run -m pytest` executes the full suite (scope with `-k pattern` when iterating) and `uv run coverage report --omit=test/* --sort=miss -m` exports `coverage.json` when you need machine-readable coverage. `make build` produces a wheel via `uvx` for packaging. For runtime deployment/runbook steps, follow `README.md`.

## Coding Style & Naming Conventions
Follow Ruff + Black-compatible formatting: 4-space indentation, 120-char lines, and import sorting enforced by Ruff. Prefer explicit type hints (mypy strictness is enabled) and Pydantic models for request/response shapes. Name async entrypoints with `_async` suffixes, FastAPI routers as `router`, and files using `snake_case`.

## Dependency Management
- **Package Manager**: uv (modern Python package manager)
- Dependencies defined in `pyproject.toml`
- Lock file: `uv.lock`
- Check dependency consistency: `uv lock --locked`

## Testing Guidelines
Testing is built around **pytest** with strict asyncio support, and the goal is to produce **meaningful, behavior-focused tests** rather than chasing shallow coverage numbers. All tests live under the top-level `test/` directory and must mirror the structure of `src/` (e.g., `src/services/foo/bar.py` → `test/services/foo/test_bar.py`).

### Principles for Writing High-Quality Tests
- **Test behavior, not implementation details.** Focus on observable inputs/outputs, side effects, persisted state, emitted events, and integration boundaries. Avoid asserting private internals or relying excessively on mocks unless isolating external systems.
- **Meaningful assertions only.** Every test must verify correctness—not merely execute lines. Assertions should compare real values, error messages, HTTP responses, state transitions, or schema validation results.
- **Cover all important branches.** For each function or agent behavior, include:
  - Happy-path cases
  - Error and exception paths
  - Boundary conditions
  - Alternative control-flow branches (`if/elif/else`, retries, fallbacks)
  - Edge cases (empty inputs, unexpected formats, None-handling)
- **Regression tests are mandatory** whenever touching agents, integrations, Supabase RPC functions, or workflow orchestration logic. If a bug is found, write a failing test first.

### Test Structure & Naming
- Each module should have a corresponding test file: `test_<module>.py`.
- Name tests with explicit intent: `test_returns_403_for_unauthorized_user`, `test_process_job_handles_empty_payload`, etc.
- Keep tests small and focused—one behavior per test.
- Use fixtures for shared setup, mocks for external resources, and dependency injection to keep units isolated.
- Async code should use `pytest.mark.asyncio` or async fixtures.

### Isolation & External Systems
- Network calls, Supabase queries, Edge Function invocations, OpenAI API calls, browser automation, and file I/O must be mocked unless explicitly performing an integration test.
- Integration tests should be placed in clearly marked directories and run conditionally.
- Do not rely on live cloud systems in CI.

### Coverage Expectations
- Aim for **≥80% meaningful coverage**—prioritizing business logic, agents, orchestration flows, integrations, and data transformation layers.
- Generate coverage via:
  ```bash
  uv run coverage run -m pytest
  ```

### When Adding or Modifying Code
1. Identify new branches or behaviors introduced.
2. Add targeted tests covering each branch.
3. Add regression coverage for any bug fixes.
4. Keep tests deterministic; avoid randomness and timing-dependent assertions.
5. After implementing a new feature, validate it through the CLI (`examples/workspace_cli/workspace_cli.py`).
6. CLI validation does not need to match a fixed smoke script exactly; choose commands/flags/args that best exercise the feature you changed.

## Configuration and Secrets
Store secrets in `.env` files (never commit). Reference via `pydantic-settings` in `src/config`.

Required environment variables:
- `HOLA_AGENT_API_KEY`: API auth key validated by all FastAPI services via `X-API-Key`
- `OPENAI_API_KEY`: For General Agent and LLM features
- `SUPABASE_URL`, `SUPABASE_API_KEY`: For Supabase integration
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`: For S3 uploads
- `POSTGRES_URL`: For pgvector database
- `SANDBOX_REMOTE_HOST_URL`, `SANDBOX_REMOTE_HOST_API_KEY`: Required when using `SANDBOX_DEFAULT_PROVIDER=docker_container`

## Observability
The project includes a comprehensive observability stack:

- **OpenTelemetry Collector** (port 4317/4318): Metrics and traces collection
- **Loki** (port 3100): Log aggregation
- **Grafana** (port 3001): Visualization dashboard
  - Default credentials: admin/admin123

Services are instrumented with OpenTelemetry for distributed tracing.

### Logging Rules (Grafana/Loki)
- Configure process-wide logging once in each API/service entrypoint with `configure_root_logging(service_name="...")`.
- Use a stable service name per service process (for example `holaboss-session-worker`, `holaboss-projects`) so Loki filtering by `service_name` is reliable.
- In modules, use `logger = logging.getLogger(__name__)`; do not attach handlers in leaf modules.
- Prefer parameterized logging over f-strings in logger calls.
- Always include structured `extra` fields for important logs, especially:
  - `event`: stable dot-delimited event key (for example `session_worker.poll_cycle`)
  - `outcome`: `start|success|error|retry|stop|dropped|not_found`
  - IDs when available: `request_id`, `session_id`, `profile_id`, `sourcing_request_id`, `worker_index`
- For exception paths inside `except` blocks, use `logger.exception(...)` instead of `logger.error(..., exc_info=True)`.
- Do not use `traceback.format_exc()` inside log messages or raised error strings; log the exception once and raise a clean typed error.
- Do not use `print(...)` in runtime service paths; use logger calls.
- Keep log messages short and consistent; put variable data in arguments and `extra`, not interpolated message text.
- Request-scoped APIs should propagate `X-Request-ID` and include request context middleware so logs can be correlated end-to-end.

Example preferred pattern:
```python
logger.info(
    "Created sourcing request %s",
    request_id,
    extra={
        "event": "sourcing.request.create",
        "outcome": "success",
        "sourcing_request_id": request_id,
    },
)
```

## Key Documentation
- `AGENTS.md`: Repository guidelines and conventions
- `docs/GENERAL_AGENT_ARCHITECTURE.md`: Comprehensive General Agent architecture
- `docs/plans/`: Implementation plans and designs

## Commit & Pull Request Guidelines
Commit history follows Conventional Commits (`feat:`, `fix:`, `migrate:`, `chore:`, etc.) and must use a detailed, structured message format.

Commit message format:
1. First line: `<type>: <imperative summary>` scoped to one cohesive concern.
2. Blank line.
3. Bullet list describing what changed and why (APIs, models, migrations, deletions, wiring changes, behavior changes).
4. Include validation coverage in the body when relevant (tests/lint/commands run).

Example pattern:
```text
feat: add cronjobs API and expand proactive analyst bootstrap context

- add a new FastAPI cronjobs service with health and CRUD/list endpoints
- add typed cronjobs client helpers and API-key handling
- update proactive analyst bootstrap context to include profile cronjobs
- add/adjust tests for API, client, and prompt behavior
```

PRs should describe context, validation commands (e.g., `make check`, `uv run pytest`), linked issues, and screenshots/log excerpts for API or UI-affecting work. Highlight any Supabase branch or migration impacts and note required environment tweaks.

## Git Workflow
- Commit messages follow the detailed Conventional Commit format defined above (title + explanatory bullet body)
- Keep commits focused on single concerns
- Run `make check` before pushing
- PRs should describe context, validation commands, and any migration impacts

## Security & Configuration Tips
Store Supabase keys, OpenAI tokens, and cloud credentials in the repo-root `.env` (or a symlinked `.env` in worktrees) or your secret manager; reference them through `src/config` settings classes. All Supabase schema or function work must go through the Supabase MCP interface before promotion—no local SQL files are required when applying changes via MCP. For local Supabase bootstrap and deployment steps, follow `README.md`.
