# Backlog

## Replace OpenCode Harness With Pi Agent

Current state:

- The runtime already has a harness seam.
- Harness selection and dispatch live primarily in [runtime/src/sandbox_agent_runtime/runner.py](/Users/jeffrey/Desktop/hola-boss-oss/runtime/src/sandbox_agent_runtime/runner.py).
- The current harnesses are `opencode` and `agno`.
- `opencode` is the default non-OSS harness and owns more than just model execution.

Important files:

- [runtime/src/sandbox_agent_runtime/runner.py](/Users/jeffrey/Desktop/hola-boss-oss/runtime/src/sandbox_agent_runtime/runner.py)
- [runtime/src/sandbox_agent_runtime/api.py](/Users/jeffrey/Desktop/hola-boss-oss/runtime/src/sandbox_agent_runtime/api.py)
- [runtime/src/sandbox_agent_runtime/product_config.py](/Users/jeffrey/Desktop/hola-boss-oss/runtime/src/sandbox_agent_runtime/product_config.py)
- [runtime/src/sandbox_agent_runtime/hb_cli.py](/Users/jeffrey/Desktop/hola-boss-oss/runtime/src/sandbox_agent_runtime/hb_cli.py)

### What OpenCode Currently Owns

- sidecar startup and readiness checks
- harness session creation and reuse
- MCP server registration
- event stream normalization into runtime output events
- provider/model config persistence in `opencode.json`

### Proposed Approach

Do not replace `opencode` in one shot. Introduce `pi` as a third harness first, then switch defaults later.

Initial work:

1. Add `pi` to `_SUPPORTED_HARNESSES` in [runtime/src/sandbox_agent_runtime/runner.py](/Users/jeffrey/Desktop/hola-boss-oss/runtime/src/sandbox_agent_runtime/runner.py).
2. Add `_execute_request_pi(request)` alongside the current harness executors.
3. Add final dispatch for `pi` in the runner.
4. Add harness readiness handling for `pi` in [runtime/src/sandbox_agent_runtime/api.py](/Users/jeffrey/Desktop/hola-boss-oss/runtime/src/sandbox_agent_runtime/api.py).
5. Update CLI/runtime-info defaults once `pi` is viable.

### Pi Harness Work Items

- define a `pi` runtime config object analogous to the current OpenCode runtime config
- implement `pi` readiness/bootstrap logic
- implement `pi` session creation / existence / reuse mapped to `harness_session_id`
- implement `pi` submit/stream execution
- implement `pi` event mapping into runtime output events
- update runtime status endpoints to report `pi` state correctly
- add tests for harness selection, readiness, execution, session reuse, and event mapping

### Main Open Question

Can `pi` support the same MCP/tool integration model as `opencode`?

- If yes, this is mostly an adapter/integration project.
- If no, `pi` is not a drop-in replacement and the runtime will need either:
  - a reduced feature mode for `pi`, or
  - a new tool integration layer that is not OpenCode-specific.

### Suggested Migration Order

1. Add `pi` as an optional harness.
2. Keep `agno` and `opencode` unchanged.
3. Reach feature parity for the `pi` execution path.
4. Change the default non-OSS harness from `opencode` to `pi`.
5. Remove `opencode` only after the runtime status, streaming, and MCP/tool flows are confirmed equivalent.
