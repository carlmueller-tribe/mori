# Version History

Mori is built in iterative versions, each adding a named capability layer. The codenames
describe what the agent gains with each version.

| Version | Codename | Released | What it gained | Key design decision |
|---------|----------|---------|---------------|-------------------|
| [v0.1](v01-it-runs.md) | **It Runs** | 2026-04-19 | Types · Loop · Tools · Anthropic adapter | Pydantic v2 for all types; async from day 1 |
| [v0.2](v02-it-sees.md) | **It Sees** | 2026-04-25 | Observability · Control · CLI · MCP | Real-time vs buffered sinks; ControlBounds extracted from loop |
| [v0.3](v03-it-remembers.md) | **It Remembers** | 2026-04-26 | 4-layer memory · Retrieval pipeline · SQLite | 4-stage retrieval; recency × relevance composite scoring |
| [v0.4](v04-it-learns.md) | **It Learns** | 2026-04-29 | Skills module · Budget manager · Compaction | Progressive disclosure; 6-stage ordered compaction |
| [v0.5](v05-its-governed.md) | **It's Governed** | *(in progress)* | Permissions · Checkpoints · Hooks | ESCALATE → PAUSE → resume flow |
| [V1 Roadmap](v1-roadmap.md) | — | *(planned)* | Compliance · Plugins · Integration · Pi patterns | Full governance layer |
