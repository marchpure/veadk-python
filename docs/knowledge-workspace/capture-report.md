# Knowledge Workspace V1 — STEP 2A Capture and Interaction Report

## Route/state coverage

`frontend/src/features/knowledge-workspace/test-fixtures/captures.ts` records
all 22 prototype state URLs. Production routing intentionally maps only the
server-backed state families (`welcome`, `skill_new`, `draft_*`, `pub_*`);
prototype scenario names and business outcomes remain test-fixture data only.

Automated capture fixture check: PASS (22 unique state URLs).

## Visual regression

The capture harness compares each 1920×1080 production capture with its
downloaded prototype reference using an RGB per-pixel absolute delta. It runs
against a test-only BFF contract fixture; it is not real-service E2E evidence.

| State family | States | Differing-pixel ratio | Mean RGB delta | Classification |
| --- | ---: | ---: | ---: | --- |
| Welcome | 1 | 48.6% | 6.61 | Conversation entry shell differs; no prototype business data copied |
| Draft base/success/failure/SOP | 5 | 69.6% | 4.32–4.50 | Structural/artifact content differs |
| Draft permission/connection/upgrade | 3 | 69.5% | 5.17–12.25 | Route state is represented; prototype demo content differs |
| Draft modal states | 4 | 72.5–73.5% | 8.32–11.33 | Server-backed modal shell differs from prototype demo panels |
| Published base | 1 | 16.2% | 1.68 | Shared shell is close; server-backed revision content differs |
| Published modal states | 4 | 100.0% | 86.94–87.86 | Route modal is represented without fabricated publication data |
| Skill-new states | 4 | 43.9% | 6.16 | Creation rail is represented; form/content differs |

Overall result: the capture harness PASS means all 22 captures and comparisons
completed. The visual diff is intentionally classified as NOT GREEN: these
are honest mismatches against a richer prototype, not a claim of pixel-perfect
parity.

Per-state measurements:

| # | Route/state | Differing-pixel ratio | Mean RGB delta |
| ---: | --- | ---: | ---: |
| 1 | `welcome` | 48.6% | 6.61 |
| 2 | `draft_dash_anta` | 69.6% | 4.35 |
| 3 | `draft_dash_anta&run_state=success` | 69.6% | 4.36 |
| 4 | `draft_dash_anta&run_state=success&modal=publish` | 72.7% | 11.33 |
| 5 | `draft_dash_anta&run_state=failed` | 69.6% | 4.50 |
| 6 | `draft_dash_anta&state=permission` | 69.5% | 12.23 |
| 7 | `draft_dash_anta&state=connection_error` | 69.5% | 12.25 |
| 8 | `draft_dash_anta&state=upgrade` | 69.5% | 5.17 |
| 9 | `draft_dash_anta&modal=advanced` | 72.5% | 8.32 |
| 10 | `draft_dash_anta&modal=test_records` | 73.5% | 8.49 |
| 11 | `draft_dash_anta&modal=tools` | 72.5% | 10.85 |
| 12 | `pub_dash_anta` | 16.2% | 1.68 |
| 13 | `pub_dash_anta&modal=agent` | 100.0% | 87.84 |
| 14 | `pub_dash_anta&modal=share_run` | 100.0% | 87.86 |
| 15 | `pub_dash_anta&modal=instructions` | 100.0% | 87.86 |
| 16 | `pub_dash_anta&modal=versions` | 100.0% | 86.94 |
| 17 | `draft_sop_bluetooth` | 69.6% | 4.35 |
| 18 | `draft_sop_haidilao` | 69.6% | 4.32 |
| 19 | `skill_new` | 43.9% | 6.16 |
| 20 | `skill_new&scenario=anta` | 43.9% | 6.16 |
| 21 | `skill_new&scenario=zhiji` | 43.9% | 6.16 |
| 22 | `skill_new&scenario=haidilao` | 43.9% | 6.16 |

The first percentage column is the differing-pixel ratio reported by
`report.json`; the table preserves the exact per-state classification while
the JSON contains the raw pixel counts and dimensions.

## Interaction checklist

| Interaction | Implementation path | Evidence |
| --- | --- | --- |
| Add connection | Dynamic JSON Schema modal → `POST /connections` | Contract client + boundary tests |
| Multi-select connections | `SkillNewView` reads BFF `ConnectionProfile[]` | Contract client + boundary tests |
| Upload task input | File picker → `POST /uploads` with progress and digest | Browser contract fixture + contract test |
| Generate | `POST /skills/drafts` → `POST /generate` | Browser contract fixture |
| SSE conversation | `GET /invocations/{id}/events` | Normalized event union, Last-Event-ID reconnect |
| Failure retry | Error code mapping + explicit retry action | Browser contract fixture + page implementation |
| Refresh recovery | URL `draftId` → `GET draft` + revisions; query cache only for reads | Browser contract fixture |
| Versions | `GET revisions` + immutable digest display | Browser contract fixture |
| Publish | `POST /skill-revisions/{id}/publish` | Browser contract fixture |
| Return path | Studio breadcrumb + browser history / `popstate` | Browser contract fixture |
| Directory geometry | Studio 48px nav, 248px directory, responsive main pane | Capture harness + screenshots |

## Browser evidence

`frontend/tests/knowledgeWorkspaceE2E.mjs` is a test-only Playwright contract
fixture. It intercepts the same-origin BFF and verifies the UI contract at
1440×900 and 390×844, including upload, forced stream disconnect, explicit
Last-Event-ID reconnect, retry, publish, refresh recovery, and return path.
Both runs passed with `invocation_count: 3` and `published: true`.

Real authenticated desktop and narrow visual/interaction acceptance remains
deferred until the BFF, Connection Service, and AutoSkill Adapter are deployed
together. `STEP2A_FROZEN` is retained; the fixture must not be interpreted as
real-service completion.
