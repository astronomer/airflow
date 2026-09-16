# House rules

A deliberately thin starting context, so there is room for the agent to learn.

- Write **Dag** in prose. Keep `DAG`, `dag_id` and `dag` as-is in code.
- Never add a new `raise AirflowException(...)`. Prefer a built-in or a dedicated class.
- No new docstrings.
