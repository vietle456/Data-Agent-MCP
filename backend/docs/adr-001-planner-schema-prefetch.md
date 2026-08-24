# ADR-001: PlannerNode — Eager Schema Pre-fetch (2 LLM Calls → 1)

**Date:** 2026-08-20  
**Status:** Accepted  
**Files affected:**
- `app/agent/nodes.py` — `PlannerNode`
- `app/prompt/prompt.py` — `PLANNER_SYSTEM_PROMPT`

---

## Context

The original `PlannerNode` used a two-call LLM pattern:

1. **Call 1** — LLM receives the user question and decides whether to call the `inspect_db_schema` tool. If it does, the tool is invoked and the schema result is collected.
2. **Call 2** — LLM receives the original messages + the schema result and produces the analytical plan.

This pattern was idiomatic LangChain tool-use but introduced an extra LLM round-trip on every planning step.

## Decision

Replace the two-call pattern with **eager schema pre-fetching**:

- `inspect_db_schema` is resolved once at `PlannerNode.__init__` time.
- On every `__call__`, the schema is fetched directly in Python (`self._schema_tool.invoke({})`), **before** the LLM is called.
- The schema is injected as plain text into the `HumanMessage` prompt.
- The LLM makes a **single call** and goes straight to producing the plan.

Additionally, the planner output format was changed from plain text to **JSON** to make downstream parsing reliable:

```json
{
  "intent": "Code execution",
  "steps": [
    { "type": "SQL_QUERY", "description": "..." },
    { "type": "PYTHON",    "description": "..." },
    { "type": "ANSWER",    "description": "..." }
  ]
}
```

The `intent` field (`"Direct answer"` | `"Code execution"`) is used by the `direct_answer` router to decide the next graph edge.

---

## Trade-offs

### ✅ Pros

| Point | Detail |
|---|---|
| Halved LLM latency | One fewer round-trip. Typically saves 1–3 seconds per plan. |
| Lower token cost | One fewer prompt + completion billed at scale. |
| Simpler code | No tool-call parsing loop or message-list stitching. |
| No hallucinated tool args | LLM previously could pass wrong args to `inspect_db_schema`. Now the call is made with controlled Python args. |
| Cleaner LLM output | Model is never tempted to emit a tool call instead of a plan. |

### ⚠️ Cons

| Point | Detail |
|---|---|
| Schema always fetched | For intent-free questions (e.g. "what is standard deviation?"), schema fetch is wasted. |
| Unconditional eager fetch | If `inspect_db_schema` is slow (large remote DB), this cost is paid on every request. |
| Lost adaptive tool-use | The original design let the LLM reason about whether it needs schema. That intelligence is removed. |
| `llm_with_tools` binding misleading | Planner never calls tools during inference now. A plain `llm` would be cleaner. |
| Args hardcoded to `{}` | Original flow let LLM pass specific table names (e.g. `{"table": "orders"}`). Now the full schema is always fetched. |

---

## Future Considerations

- **Schema caching** — if `inspect_db_schema` becomes expensive, cache the result (e.g. per-session or with a short TTL) to avoid redundant DB introspection calls.
- **Pass plain `llm` to PlannerNode** — since the planner no longer calls tools during inference, removing the tool binding would reduce prompt size and eliminate any chance of the model attempting a tool call.
- **Selective schema injection** — for multi-database setups, consider fetching only the relevant tables' schemas based on a keyword match against the user question before calling the LLM.
