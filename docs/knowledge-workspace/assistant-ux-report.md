# Knowledge Workspace Assistant UX verification

Status: frozen with an external AutoSkill blocker. The implementation and
browser acceptance are complete; fresh-session MCP tool selection in the
official AutoSkill service remains nondeterministic.

## Requirement matrix

| Requirement | Evidence | Result |
| --- | --- | --- |
| Semantic AutoSkill event mapping and parent/call linkage | `test_autoskill_adapter.py` | Pass |
| Safe planning, tool, summary, state, and error payloads | adapter and service contract tests | Pass |
| Durable multi-turn restore and event deduplication | route, reducer, and component tests | Pass |
| Cancel, retry, reconnect, and numeric `Last-Event-ID` | service, client, and reducer tests | Pass |
| Markdown final answer with raw HTML disabled | component contract and production build | Pass |
| Desktop 1440×900 and mobile 390×844 layout | real screenshots below | Pass |
| Real official AutoSkill lifecycle | `real-autoskill-mcp.json` | Pass: create, invoke, and update; Turns 1–22 |
| Real MCP Action/Observation | matching Connection Service audit in `real-autoskill-mcp.json` | Pass: `hackernews.get_max_item_id`, `ok: true` |
| Real browser Markdown, refresh, reconnect, and dedupe | `real-browser-e2e.json` | Pass |
| Same invocation satisfies both rows above | External blocker | `OFFICIAL_AUTOSKILL_FRESH_SESSION_TOOL_SELECTION_NONDETERMINISTIC` |

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

- `evidence/assistant-ux/assistant-real-desktop-1440x900.png`
  (`522eb7089a357cee65e0e101cb71d40df0ebe6200225c1184705c26421dec4d7`)
- `evidence/assistant-ux/assistant-real-mobile-390x844.png`
  (`7552732cb6b15bfd6c9da4373652a7f2d0fa0e73688b73bcab3699554a350d3c`)
- `evidence/assistant-ux/assistant-desktop-1440x900.png`
  (`066102e6be045fd9125eda3326df0875c3386c6360ab027357381de0504371c7`)
- `evidence/assistant-ux/assistant-mobile-390x844.png`
  (`8eaa67ba0250bbfecbeb9af100d4469b33068e1a410056928dceaba2fd97b7c2`)

The `assistant-real-*` screenshots use the official AutoSkill endpoint through
the real BFF. The two screenshots without `real` in their names remain
deterministic contract-fixture regression evidence.

## Real-live acceptance

The official endpoint
`https://test-bytebrain.byted.org/openapi/autoskill/v1/health` returned
`{"status":"ok","state_mode":"stateful"}` on 2026-08-28.

`real-autoskill-mcp.json` records a sanitized real lifecycle. Create ran for
Turns 1–8, invoke ran for Turns 9–17, and update ran for Turns 18–22. Each
stage produced semantic Action/Observation events and a terminal Markdown
answer. The invoke request has a matching Connection Service audit for
`hackernews.get_max_item_id` with `ok: true`. The HTML artifact was validated,
and the differing pre/post Skill ZIP hashes prove the update persisted.

`real-browser-e2e.json` records a separate real BFF/browser acceptance run.
A transparent test proxy forwarded the real SSE bytes and closed the first
downstream stream after three complete event frames. The UI exposed
“继续接收”, then reconnected with numeric `Last-Event-ID: 2`. The real stream
contained 15 browser-safe events, including two upstream Turns, five activity
starts, three completions, and one final answer. The completed conversation had
one user turn and seven rendered activities both before and after navigation.
Before restoring, the test cleared localStorage and sessionStorage;
the final Markdown heading/list/table and full activity history were restored
from the BFF without duplicates. No response, event, or result was synthesized.

Raw identifiers, credentials, lease material, internal runtime URLs, and raw
tool payloads are excluded from committed evidence.

The two successful evidence files refer to different AutoSkill invocations and
are not combined into a false same-invocation pass. A fresh official run
confirmed that the BFF bound the Connection lease and MCP URL to the same
AutoSkill request ID, but that official AutoSkill invocation did not expose the
configured MCP tool and produced no matching Connection action audit. This is
recorded as
`OFFICIAL_AUTOSKILL_FRESH_SESSION_TOOL_SELECTION_NONDETERMINISTIC`; it is an
external service blocker rather than a continuing blocker for this branch.

## Final verification

- Backend: 66 Knowledge Workspace tests passed.
- Frontend: 862 tests passed.
- TypeScript: `tsc --noEmit` passed.
- Production bundles: Studio and website integration builds passed; only the
  repository's existing chunk-size warnings remain.
- Contract: `tools/validate_knowledge_workspace.py` passed.
- Quality gates: Ruff check/format and Gitleaks passed.

ASSISTANT_UX_FROZEN_WITH_EXTERNAL_AUTOSKILL_BLOCKER
