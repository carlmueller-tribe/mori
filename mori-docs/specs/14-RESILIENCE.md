# 14: Resilience and Fault Tolerance

**Status:** Future (not scheduled)
**Module:** `mori.resilience`
**Dependencies:** Specs 01, 02, 07, 08

---

## 1. Purpose

Durable execution, distributed fault tolerance, and long-lived workflow coordination. This spec defines how Mori's existing resilience primitives (CheckpointStore, PAUSED state, ThreadId, HookRegistry) can be backed by Temporal to eliminate checkpoint polling, gain a workflow audit trail, and distribute retries across workers — without changing Mori's public API.

All Temporal integration is opt-in. The native runtime remains the default; Temporal is a backend choice.

---

## 2. Motivation

Mori already has the conceptual building blocks of a durable workflow engine:

| Mori primitive | What it does today | What Temporal does natively |
|---|---|---|
| `CheckpointStore` | Serialize/restore MoriState to a backend | Workflow state is implicit in Temporal's execution history |
| `RunStatus.PAUSED` + `loop.resume()` | Save checkpoint, poll for external signal | Temporal Signal — live workflow waits for an event, no polling |
| `ThreadId` | Durable conversation identifier | Temporal Workflow ID — globally addressable, queryable |
| `HookRegistry` lifecycle events | In-process `asyncio.wait_for` callbacks | Temporal Activity with retry policy + timeout |
| `_phase_*` functions | Sequential async phase calls | Temporal Activity per phase — independent retry, timeout, worker |

The PAUSED → resume flow is the clearest fit: it is a manual re-implementation of the Temporal Signal pattern. Replacing the checkpoint-poll loop with a live Temporal workflow eliminates polling latency, gives a UI audit trail, and makes approval gates a first-class primitive.

---

## 3. Integration Points

### 3.1 TemporalCheckpointStore

The `CheckpointStore` protocol (Spec 07) gains a fifth backend:

```python
class TemporalCheckpointStore(CheckpointStore):
    """
    Maps CheckpointStore operations onto Temporal workflow state.

    save()       → start or signal a Temporal workflow
    load_latest() → query the latest workflow state via Temporal Query
    load()       → query a specific workflow run by checkpoint_id
    list()       → list workflow executions by thread_id search attribute
    delete()     → terminate the workflow
    """
```

This is the **natural seam** — it slots into the existing protocol without touching the loop. A team adds `TemporalCheckpointStore` the same way they would switch from `SQLiteCheckpoints` to `PostgresCheckpoints`.

**Mapping:**
- `CheckpointId` → Temporal Run ID
- `ThreadId` → Temporal Workflow ID
- `MoriState.model_dump_json()` → payload stored in Temporal's workflow history (existing serialization, no change)

### 3.2 PAUSED State → Temporal Signal

The current PAUSED flow:
1. Agent hits ESCALATE → loop sets `status = RunStatus.PAUSED`
2. Checkpoint is saved to the store
3. External caller polls `load_latest()` until state changes
4. `loop.resume()` restores checkpoint and continues

With Temporal:
1. Agent hits ESCALATE → Temporal workflow pauses at a `wait_for_signal` activity
2. No checkpoint polling — the workflow is live, waiting for a `resume` Signal
3. External caller sends `client.signal_workflow(thread_id, "resume", input)`
4. Workflow continues from the exact point it paused

The Mori API (`loop.pause()`, `loop.resume()`) stays identical. The runtime detects a `TemporalCheckpointStore` and routes through signals instead of the poll loop.

### 3.3 AgentLoop Phases → Temporal Activities

Each runtime phase maps to a Temporal Activity:

```python
@activity.defn(name="mori_phase_retrieve")
async def phase_retrieve_activity(state: MoriState) -> MoriState: ...

@activity.defn(name="mori_phase_plan")
async def phase_plan_activity(state: MoriState) -> MoriState: ...

@activity.defn(name="mori_phase_act")
async def phase_act_activity(state: MoriState) -> MoriState: ...
```

Each activity gets its own:
- **Retry policy** (e.g. act retries 3×, retrieve retries 1×)
- **Schedule-to-close timeout** (per-phase budget)
- **Worker assignment** (plan and act can run on separate workers)

`_run_from_state()` becomes a Temporal Workflow — durable execution replaces explicit checkpoint save/restore. The loop structure already mirrors a Workflow; this formalizes it.

### 3.4 ThreadId → Temporal Workflow ID

`ThreadId` is already a durable, opaque conversation identifier. Mapping it 1:1 to the Temporal Workflow ID makes every Mori thread queryable, signal-able, and continuable from Temporal's UI or any Temporal client — no additional identifier needed.

### 3.5 HookRegistry → Temporal Activity Dispatches

Hook handlers registered for lifecycle events currently run in-process with `asyncio.wait_for`. As Temporal Activities they gain:
- **Automatic retries** on failure
- **Per-hook timeouts** enforced by Temporal, not asyncio
- **Distributed execution** — hooks can run on separate workers
- **Audit trail** in Temporal UI

```python
@activity.defn(name="mori_hook_{event_name}")
async def hook_activity(event: MoriEvent) -> None: ...
```

The `HookRegistry` dispatches activities instead of coroutines when a `TemporalClient` is configured.

---

## 4. Package Shape

```
mori/
└── resilience/                 # Spec 14: Temporal integration
    ├── __init__.py
    ├── checkpoint.py           # TemporalCheckpointStore
    ├── workflow.py             # MoriAgentWorkflow (Temporal Workflow)
    ├── activities.py           # Phase + hook activities
    └── client.py               # TemporalClient wrapper + signal helpers
```

**Optional dependency:** `temporalio` — not in core requirements. Added under `mori[temporal]` extras.

---

## 5. API

```python
# Drop-in replacement for any CheckpointStore backend
from mori.resilience import TemporalCheckpointStore

loop = AgentLoop(
    model=model,
    tools=tools,
    checkpointer=TemporalCheckpointStore(
        client=temporal_client,
        task_queue="mori-agents",
    ),
)

# pause/resume API is unchanged
checkpoint_id = await loop.pause(run_id)
result = await loop.resume(thread_id, input={"approval": True})
```

---

## 6. Migration Path

| Stage | What changes | API impact |
|---|---|---|
| 1. TemporalCheckpointStore | Swap backend; PAUSED uses signals | None — same `CheckpointStore` protocol |
| 2. Phase activities | Phases run as Temporal Activities | None — same `AgentLoop.run()` surface |
| 3. Full workflow | `_run_from_state` is a Temporal Workflow | None — same public API, durable execution underneath |
| 4. Hook activities | Hooks dispatch as Temporal Activities | Optional — controlled by `HookRegistry` config |

Each stage is independently deployable. A team can adopt stage 1 (TemporalCheckpointStore) without committing to stage 3 (full workflow).

---

## 7. Out of Scope

- Multi-agent coordination via Temporal (child workflows) — deferred to a multi-agent spec
- Temporal Cloud auth and namespace management — deployment concern, not library concern
- Replacing the native runtime for teams that don't need Temporal — native loop stays default

---

## 8. Test Criteria

- [ ] `TemporalCheckpointStore` satisfies the `CheckpointStore` protocol contract (same tests as other backends)
- [ ] `loop.pause()` with `TemporalCheckpointStore` sends a pause signal rather than polling
- [ ] `loop.resume()` sends a Temporal Signal; workflow continues from paused state
- [ ] `ThreadId` maps 1:1 to Temporal Workflow ID with no collision
- [ ] Phase activities execute in phase order and pass MoriState between them
- [ ] Activity retry policies are enforced per phase configuration
- [ ] Hook activities fire on lifecycle events and are retried on failure
- [ ] Swapping from `SQLiteCheckpoints` to `TemporalCheckpointStore` requires no change to `AgentLoop` call sites
