# Chat Mode

Mori is autonomous by default — `agent.run(task)` runs to completion. In v0.7,
Mori is also chat-capable: the agent can pause mid-run to ask the user a
question and resume after the user responds.

## The `ask_user` tool

`ask_user(question: str) -> str` is a native tool registered automatically on
every Mori agent (unless `.disable_native_tool("ask_user")` is called).

When the agent invokes it, the loop:

1. Transitions to `RunStatus.PAUSED` with `paused_reason="await_user_input"`
2. Sets `state.paused_prompt = question`
3. Saves a checkpoint
4. Fires `turn.end` with `reason=PAUSED_AWAIT_USER`
5. Returns control to the caller

## Caller pattern

```python
result = await agent.run("Migrate the user table")
while result.status == RunStatus.PAUSED and result.paused_prompt:
    answer = input(f"{result.paused_prompt}\n> ")
    result = await agent.resume(result.thread_id, answer)
```

The user's response is injected as the paused tool call's result so the agent
sees it as `ask_user`'s return value.

## When NOT to use ask_user

The agent should call `ask_user` only when it cannot proceed without input.
Repeated asks for things the agent could figure out itself are a sign of
prompt or skill design issues, not a runtime issue.

## Requirements

- A checkpointer must be configured (`.checkpointer("memory")` or `.checkpointer("sqlite", path=...)`); resume requires it.
- The agent must have `ask_user` registered — true by default; opt out with `.disable_native_tool("ask_user")`.
