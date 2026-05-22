# Hooks

Mori hooks are priority-ordered callbacks that fire at well-defined lifecycle
events. Each hook is one of three modes:

| Mode | Mechanism | Example |
|---|---|---|
| **Observe** | Register on a `*.after` event; return is ignored | logging, metrics, audit trail |
| **Transform** | Register on a `*.before` event; return a new payload to mutate it | adding system messages, rewriting tool args |
| **Gate** | Register on a `*.before` event; `raise HookBlock(reason)` to veto, or `raise HookRetry(feedback)` to force a retry | enforcement, output validation |

The three modes are not separate APIs — they're three ways of using the same
`@registry.hook(event, priority)` decorator.

## Event Catalog

| Event | When | Payload | Block? | Retry? |
|---|---|---|---|---|
| `turn.start` | entry to `run()` / `resume()` | `TurnStartPayload` | yes | no |
| `model.request.before` | before model invoke | `ModelRequest` | yes | yes |
| `model.response.after` | after model invoke | `ModelResponse` | — | — |
| `permission.check.after` | after permission check | `PermissionResult` | — | — |
| `tool.invoke.before` | before tool runs | `ToolCall` | yes | no |
| `tool.invoke.after` | after tool runs | `ToolResult` | — | — |
| `run.start` (legacy) | once per `run()` | `{task, run_id}` | — | — |
| `run.end` (legacy) | once per `run()` | `{status, run_id}` | — | — |
| `turn.end` | every exit of `run()` / `resume()` | `TurnEndPayload` | no | yes |

## Why hooks aren't permissions

`PermissionEngine` answers declarative questions ("can identity X do permission Y
on resource Z"). Hooks answer imperative questions ("does this specific request,
right now, in this specific shape, look wrong"). Use permissions for stable
identity/resource policy. Use hooks for content-aware, code-driven checks.

## Bounded retries

`HookRetry` is bounded by `HookConfig.max_retry_limit` (default 3). Exhaustion
sets `RunStatus.FAILED` with `error="hook_retry_exhausted"` (model.request.before)
or `"turn_end_retry_exhausted"` (turn.end).
