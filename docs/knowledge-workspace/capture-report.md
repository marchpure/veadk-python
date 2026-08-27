# Knowledge Workspace V1 — STEP 2A Capture and Interaction Report

## Route/state coverage

`frontend/src/features/knowledge-workspace/test-fixtures/captures.ts` records
all 22 prototype state URLs. Production routing intentionally maps only the
server-backed state families (`welcome`, `skill_new`, `draft_*`, `pub_*`);
prototype scenario names and business outcomes are test-fixture data only.

Automated capture fixture check: PASS (22 unique state URLs).

## Visual regression

| Viewport | Fixture baseline | Result |
| --- | --- | --- |
| Desktop 1440×900 | Contract-fixture browser run | PASS — [desktop screenshot](evidence/knowledge-workspace-desktop.png) |
| Narrow 390×844 | Contract-fixture browser run | PASS — [narrow screenshot](evidence/knowledge-workspace-narrow.png) |

The browser run captures the implemented layout and interaction sequence. It
is not a pixel-diff against the prototype capture URLs, and it does not claim
real-service completion.

## Interaction checklist

| Interaction | Implementation path | Evidence |
| --- | --- | --- |
| Add connection | Dynamic JSON Schema modal → `POST /connections` | Contract client + boundary tests |
| Multi-select connections | `SkillNewView` reads BFF `ConnectionProfile[]` | Contract client + boundary tests |
| Generate | `POST /skills/drafts` → `POST /generate` | Contract client |
| SSE conversation | `GET /invocations/{id}/events` | Normalized event union, parser, reconnect cursor |
| Failure retry | Error code mapping + explicit reconnect/retry action | Page implementation |
| Refresh recovery | URL `draftId` → `GET draft` + revisions; query cache only for reads | Page implementation |
| Versions | `GET revisions` + immutable digest display | Page implementation |
| Publish | `POST /skill-revisions/{id}/publish` | Contract client |
| Return path | Studio breadcrumb + browser history / `popstate` | Page implementation |
| Right-pane layout | Responsive `.kw-chat` shell | CSS + production build |

## Browser evidence

`frontend/tests/knowledgeWorkspaceE2E.mjs` is a test-only Playwright contract
fixture. It intercepts the same-origin BFF and verifies the UI contract at both
viewports, including a forced first-stream disconnect followed by an explicit
Last-Event-ID reconnect. Both runs passed with one invocation, two event-stream
requests, and a successful publish.

Real-click recording and real BFF evidence remain deferred until the BFF,
Connection Service, and AutoSkill Adapter are deployed together. Contract
fixtures must not be interpreted as real end-to-end completion.
