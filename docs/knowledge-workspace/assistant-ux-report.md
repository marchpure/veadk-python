# Knowledge Workspace Assistant UX verification

Status: implementation complete; real-live acceptance remains blocked.

## Requirement matrix

| Requirement | Evidence | Result |
| --- | --- | --- |
| Semantic AutoSkill event mapping and parent/call linkage | `test_autoskill_adapter.py` | Pass |
| Safe planning, tool, summary, state, and error payloads | adapter and service contract tests | Pass |
| Durable multi-turn restore and event deduplication | route, reducer, and component tests | Pass |
| Cancel, retry, reconnect, and numeric `Last-Event-ID` | service, client, and reducer tests | Pass |
| Markdown final answer with raw HTML disabled | component contract and production build | Pass |
| Desktop 1440×900 and mobile 390×844 layout | screenshots below | Pass with contract fixtures |
| Real official AutoSkill lifecycle | `tools/autoskill_real_smoke.py` | Blocked: update stream stopped producing events |
| Real MCP Action/Observation and browser refresh/reconnect | prior integration evidence | Blocked: official agent did not select the configured MCP tool |

## AutoSkill ChatPanel comparison

| Capability | Native ChatPanel | Knowledge Workspace Assistant |
| --- | --- | --- |
| Message persistence | AutoSkill message/state APIs | BFF-owned durable invocation events |
| Execution display | Planning and action records | Turn-aware, ordered, collapsible activity timeline |
| Tool correlation | Provider call metadata | Action/Observation merged by `call_id` and `parent_id` |
| Final response | Markdown | Existing project Markdown renderer with raw HTML disabled |
| Recovery | Stateful history | Refresh restore, dedupe, cancel, retry, and `Last-Event-ID` reconnect |
| Controls | Model/mode/upload controls | Intentionally omitted to preserve Workspace product boundaries |
| Privacy boundary | Provider payload available to native UI | BFF allowlist plus credential, lease, internal URL, reasoning, and raw-output redaction |

Borrowed: ordered messages, visible execution progress, Markdown responses, and
stateful recovery. Intentionally omitted: model switching, mode switching, and
Skill upload controls. Improved: durable BFF-owned conversation history,
semantic event trees, paired tool activity, explicit recovery states, compact
completed timelines, and stricter browser-safe redaction.

## Visual evidence

- `evidence/assistant-ux/assistant-desktop-1440x900.png`
  (`066102e6be045fd9125eda3326df0875c3386c6360ab027357381de0504371c7`)
- `evidence/assistant-ux/assistant-mobile-390x844.png`
  (`8eaa67ba0250bbfecbeb9af100d4469b33068e1a410056928dceaba2fd97b7c2`)

These screenshots use contract fixtures and are not represented as real
AutoSkill evidence.

## Real-live status

The official endpoint
`https://test-bytebrain.byted.org/openapi/autoskill/v1/health` returned
`{"status":"ok","state_mode":"stateful"}` on 2026-08-28. A fresh lifecycle run
advanced through create, list, view, and invoke, then produced no terminal
event for the update stream and was stopped after eight minutes. Since the
runner only emits its redacted JSON report after the complete lifecycle, this
partial run is not counted as acceptance evidence.

The exact Connection Service configuration is not present in the current
environment, port 3417 has no listener, and no public runtime tunnel is active.
Earlier real attempts are recorded in:

- `evidence/step2-existing-replay-final.json`
- `evidence/step2-cross-session-final.json`
- `checkpoints/integration.json`

Those attempts reached the official stateful service but did not yield a
matching real Connection audit because the agent did not select the configured
MCP tool. No fixture or forced prompt is substituted for this gate. Therefore
`KNOWLEDGE_ASSISTANT_UX_FROZEN` is intentionally not declared.
