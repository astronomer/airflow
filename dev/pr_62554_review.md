# PR #62554 Review: "Simplify approach for creating dag run and task spans"

## Summary

This is a well-motivated cleanup that replaces a complex, scheduler-resident OTel tracing
implementation (long-lived span objects stored in a shared `ThreadSafeDict`, span status state
machine in the DB, multi-scheduler span handoff logic) with a much simpler fire-and-forget
approach: emit a closed span at dag run completion and open a live span around the task process
lifecycle. The result is a ~700-line net deletion with cleaner semantics. The approach is
fundamentally sound.

---

## Critical Issues

### 1. `_emit_dagrun_span` reuses the seed span's span ID (PARTIALLY FIXED)

In `dagrun.py`, the original `_emit_dagrun_span` called `override_ids(trace_id, span_id)` with
both the trace ID **and** span ID extracted from the seed span. Since `OverrideableRandomIdGenerator`
returns those override values when generating IDs for the new span, the emitted dag run span ended
up with the **same span ID** as the never-ended seed span. This gives it a duplicate identity and
will confuse trace viewers.

**Fix applied in this session:**
- `override_ids` signature changed to `override_ids(trace_id, span_id=None, ctx=None)` — span ID
  override is only set when explicitly passed.
- `_emit_dagrun_span` now calls `override_ids(seed_span_context.trace_id)` (no span ID), so the
  emitted span gets a fresh random span ID while still belonging to the same trace.
- `span.set_status` and `span.end` moved outside the `with override_ids(...)` block.
- `span.end()` now passes explicit `end_time` from `self.end_date`.

**Consequence for existing test:** `test_emit_dagrun_span_uses_context_carrier_ids` asserts
`span.context.span_id == stored_ctx.span_id` — this assertion will now fail and should be updated
to assert only `span.context.trace_id == stored_ctx.trace_id`.

### 2. The "seed span" in `DagRun.__init__` is never ended — potential span leak

```python
span = tracer.start_span("notused", context=empty_context)
```

This span is started but never ended (intentionally, per the comment). With a no-op tracer this is
harmless, but when a real SDK `TracerProvider` is configured the SDK may warn or hold a reference.
Consider using `NonRecordingSpan` directly to generate trace context without creating a recordable
span:

```python
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
gen = RandomIdGenerator()
span_ctx = trace.SpanContext(
    trace_id=gen.generate_trace_id(),
    span_id=gen.generate_span_id(),
    is_remote=False,
)
ctx = trace.set_span_in_context(trace.NonRecordingSpan(span_ctx))
carrier: dict[str, str] = {}
TraceContextTextMapPropagator().inject(carrier, context=ctx)
self.context_carrier = carrier
```

### 3. `@flush_spans()` decorator syntax is wrong

In `task_runner.py`:

```python
@flush_spans()
def main():
```

`flush_spans` is a `@contextmanager` — it is not a decorator factory. `@flush_spans()` invokes
`flush_spans()` which returns a `GeneratorContextManager`, then tries to use that as a decorator,
which will fail at call time. The correct approach is to call it explicitly inside `main()`:

```python
def main():
    with flush_spans():
        ...
```

---

## Improvements

### 4. `_make_task_span` map_index check is off-by-one

```python
if ti.map_index is not None and ti.map_index > 0:
    span_name += f"_{ti.map_index}"
```

Map index `0` is a valid mapped task instance (the first element). The check `> 0` silently omits
the index for map_index=0, creating ambiguity with non-mapped tasks. Should be `>= 0`:

```python
if ti.map_index is not None and ti.map_index >= 0:
    span_name += f"_{ti.map_index}"
```

### 5. `configure_otel` call placement in `settings.py`

Reviewer `ashb` flagged that `configure_otel()` must be called inside `initialize()` only, not at
import time. The author replied "done" but worth verifying the final diff reflects this correctly.

### 6. `_get_backcompat_config` doesn't check `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`

The endpoint backcompat check guards against `OTEL_EXPORTER_OTLP_ENDPOINT` but not
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`. Reviewer `xBis7` flagged this; author said "done" — verify
the fix is present in the latest code.

### 7. `span.end()` should use explicit `end_time`

`span.end()` without `end_time` defaults to wall-clock "now" (the time `update_state` is called),
not `self.end_date`. Since the dag run's actual end time is available:

```python
span.end(end_time=int((self.end_date or timezone.utcnow()).timestamp() * 1e9))
```

**(This is included in the fix applied in this session.)**

---

## Nits

- The seed span name `"notused"` in `__init__` should be something more descriptive like
  `"_airflow_context_seed"` in case it appears in debug output.
- `test_emit_dagrun_span_uses_context_carrier_ids` imports inside the test body rather than at the
  top — minor style inconsistency vs. the rest of the test class.
- `test_task_span_no_parent_when_no_context_carrier` passes `context_carrier=None` but
  `_make_task_span` guards with `if msg.ti.context_carrier` — worth adding a comment noting this
  is the intentional fallback path.
- The integration test rename `start_worker_and_scheduler` → `start_scheduler` should be verified
  to no longer start a worker process (task span flushing is now the worker's responsibility).

---

## PR Hygiene

- **CI:** Most checks were still in-progress at review time. CodeQL is NEUTRAL.
- **Scope:** Appropriately scoped. PR description accurately reflects what's done, including
  explicitly deferred items (deprecating `OtelTrace`, `Trace`, `EmptyTrace` classes).
- **Existing review comments:** Most from `xBis7` and `ashb` appear addressed per the author's
  replies, but items 5 and 6 above need verification.
- The deferred deprecations of old `OtelTrace`/`Trace`/`EmptyTrace` classes should be tracked in
  a follow-up issue.

---

## Changes Applied in This Session

| File | Change |
|------|--------|
| `airflow-core/src/airflow/observability/traces/__init__.py` | `override_ids(trace_id, span_id=None, ctx=None)` — span_id now optional |
| `airflow-core/src/airflow/models/dagrun.py` | `_emit_dagrun_span` — only overrides trace_id, fresh span_id, explicit end_time, set_status/end outside override_ids block |
