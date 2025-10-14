# Critical Review Fixes – Role-Based Secrets Chains (Option E)

## Final Implementation

### Why Option E (Role-Based Chains)

- Combines the explicitness of Option A with zero migration cost.
- Single source of truth (`ROLE_TO_SECRETS_CHAIN`) for all execution contexts.
- Automatic role detection keeps backward compatibility.
- Future-proof: easy to add new roles or diagnostics without touching hooks.

### Architecture

| Role | Chain | Notes |
|------|-------|-------|
| `WORKER_TASK_RUNNER` | `CLIENT_TASK_RUNNER_SECRETS_SEARCH_PATH` | Uses ExecutionAPISecretsBackend via SUPERVISOR_COMMS |
| `WORKER_SUPERVISOR` | `CLIENT_SUPERVISOR_SECRETS_SEARCH_PATH` | Environment vars + API client fallback |
| `API_SERVER`, `SCHEDULER`, `DAG_PROCESSOR`, `TRIGGERER` | `SERVER_SECRETS_SEARCH_PATH` | Direct DB access |

- `SecretsRole` enum documents all contexts.
- `ROLE_TO_SECRETS_CHAIN` populated in `airflow.secrets.__init__`.
- `_detect_secrets_role()` provides heuristics (SUPERVISOR_COMMS, env var) until callers pass explicit roles.

### Advantages

✅ Explicit chains (no scattered heuristics)

✅ Backward compatible (auto-detection still works)

✅ Worker isolation maintained (supervisor chain excludes MetastoreBackend)

✅ External secrets work everywhere (env var + custom backends prioritized)

✅ Testability improved (role detection isolated, mapping easy to assert)

✅ Clear path to evolve toward explicit role registration

### Tests Added

- `test_worker_task_runner_role`
- `test_api_server_role`
- `test_worker_supervisor_role`
- Integration tests for backend selection and connection fallback

### Backend Initialization Consolidation

**Before:**
- `ensure_secrets_loaded(default_backends)` - in airflow.configuration
- `ensure_secrets_backend_loaded()` - in task-sdk supervisor
- `initialize_secrets_backends(default_backends)` - in airflow.configuration

**After:**
- `ensure_secrets_backends(role=None, default_backends=None)` - unified API
- Supports explicit role OR auto-detection OR legacy default_backends
- Old functions kept as deprecated aliases for backward compatibility

**Benefits:**
- Single source of truth for backend initialization
- Explicit role support (no more implicit detection everywhere)
- Cleaner call sites: `ensure_secrets_backends(role=SecretsRole.SCHEDULER)`
- Backward compatible via deprecated aliases

### SupervisorAPIClientSecretsBackend

Added new backend for supervisor contexts that need connections for remote logging before SUPERVISOR_COMMS exists:

- Located at `task-sdk/src/airflow/sdk/execution_time/secrets/supervisor_api.py`
- Takes `Client` instance in constructor
- Used by `_get_remote_logging_conn` for supervisor processes
- Enables proper connection retrieval for remote log handlers on workers

### Core-Only Deployment Support

When Task SDK is not installed (core-only deployments):
- `ensure_secrets_backends()` catches `ImportError` when trying to import `_detect_secrets_role`
- Falls back to `SecretsRole.API_SERVER` → uses server chain with MetastoreBackend
- Ensures core deployments work without Task SDK package

### Next Steps (Future)

1. Optionally emit diagnostics for role detection.
2. Allow explicit role registration (Option A) built on this foundation.
3. Consider exposing `airflow secrets roles list` for debugging.


