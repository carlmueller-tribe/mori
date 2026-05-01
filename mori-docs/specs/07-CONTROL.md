# 07: Control Engine

**Status:** Draft v3
**Module:** `mori.control`
**Dependencies:** Spec 01

---

## 1. Purpose

Resource bounds and checkpointing. Mori owns both since there is no external framework dependency.

## 2. Changes from v2

Checkpointing is back in Mori (it was delegated to LangGraph in v2). The implementation is simple: serialize MoriState to JSON and store it in a pluggable backend.

## 3. Resource Bounds

```python
class ControlBounds:
    def __init__(self, config: ControlConfig) -> None: ...
    def check_bounds(self, state: MoriState) -> BoundCheckResult: ...
    def should_retry(self, error: Exception, attempt: int) -> RetryDecision: ...
    def record_progress(self) -> None: ...
```

Configuration, BoundCheckResult, RetryDecision, check order, and backoff formula are unchanged from v1 Spec 07.

## 4. Checkpoint Store

```python
class CheckpointStore(Protocol):
    """Pluggable checkpoint persistence."""
    async def save(self, state: MoriState) -> CheckpointId: ...
    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None: ...
    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None: ...
    async def list(self, thread_id: ThreadId) -> list[Checkpoint]: ...
    async def delete(self, checkpoint_id: CheckpointId) -> None: ...
```

**Included backends:**

| Backend              | Dependencies | Use Case       |
|----------------------|-------------|----------------|
| InMemoryCheckpoints  | None        | Dev/test       |
| FileCheckpoints      | None        | Local          |
| SQLiteCheckpoints    | sqlite3     | Single-user    |
| PostgresCheckpoints  | asyncpg     | Production     |

**Serialization:** MoriState is serialized via `state.model_dump_json()`. Deserialization via `MoriState.model_validate_json()`. Pydantic handles the round-trip. No pickle, no custom serializers.

## 5. Integration with Runtime

The runtime (Spec 02) calls the checkpoint store at three points:

- **On startup:** `load_latest(thread_id)` to restore a previous session
- **Every N steps:** `save(state)` for auto-checkpointing
- **On pause/completion:** `save(state)` for final state persistence

## 6. Test Criteria

All from v1 Spec 07 plus:
- [ ] MoriState round-trips through JSON serialization without data loss
- [ ] load_latest returns the most recent checkpoint for a thread
- [ ] Multiple checkpoints for the same thread are stored and listable
- [ ] FileCheckpoints creates and reads files correctly
- [ ] SQLiteCheckpoints handles concurrent access
