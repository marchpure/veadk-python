# Knowledge Workspace V1 — STEP 2A Visual Capture Report

## Evidence and method

The test-only capture fixture
`frontend/src/features/knowledge-workspace/test-fixtures/captures.ts` records
the 22 Prototype state URLs. The capture harness
`frontend/tests/knowledgeWorkspaceCapture.mjs` renders each state through the
same-origin BFF contract fixture, waits for route content to settle, asserts
the required DOM/page/modal geometry, captures at 1920×1080, and compares the
implementation PNG with the SHA-verified Prototype reference using RGB
per-pixel absolute delta.

The fixture is not shipped in production. Production code continues to read
only `/api/knowledge/v1`; no Prototype business data or mock fallback is
reachable from the production route.

Evidence:

- Implementation captures: `docs/knowledge-workspace/evidence/captures/01.png`
  through `22.png`
- Raw comparison: `docs/knowledge-workspace/evidence/captures/report.json`
- Prototype source/capture package: v2.20.8.3, recorded in
  `docs/knowledge-workspace/checkpoints/bootstrap.json`
- All captures: 1920×1080; no dimension mismatch; no state had a 100% diff

## Visual gate

The differing-pixel ratio is retained as a risk signal only. It is sensitive
to font rasterization and to the Prototype published-modal reference anomaly.
The gate below is based on the required manual side-by-side review of page
state, skeleton, hierarchy, component presence, geometry, overflow, and
responsive behavior.

Manual review and render-gate result: P0 = 0, P1 = 0. All 22 states render the intended page
or modal rather than a URL-only placeholder. No state has an empty replacement
page, main/right-pane overlap, clipping, or blocking overflow at the reviewed
desktop and narrow layouts.

The harness additionally asserts welcome cards, draft center and chat rail,
380px desktop chat geometry, skill-new form/connection/upload structure, one
visible dialog for every modal URL, and draft-center-relative inset coverage
for permission and connection-error overlays. These assertions passed for all
22 states.

| State family | States | Differing-pixel ratio | Mean RGB delta | Manual gate |
| --- | ---: | ---: | ---: | --- |
| Welcome | 1 | 32.82% | 6.57 | GREEN |
| Draft base / success / failed / SOP | 5 | 11.07–15.63% | 2.66–3.21 | GREEN |
| Permission / connection error / upgrade | 3 | 14.85–42.63% | 3.68–3.86 | GREEN |
| Draft advanced / test records / tools | 3 | 46.75–47.58% | 3.00–4.78 | GREEN |
| Draft publish gate | 1 | 53.23% | 6.36 | GREEN |
| Published base | 1 | 9.08% | 1.55 | GREEN |
| Published agent / share / instructions / versions | 4 | 17.22–36.49% | 2.33–3.19 | GREEN |
| Skill-new and scenarios | 4 | 12.13% | 3.99 | GREEN |

### Published modal reference note

The four Prototype PNGs for `modal=agent`, `modal=share_run`,
`modal=instructions`, and `modal=versions` were captured as mostly the
published base shell and do not visibly contain the corresponding modal
surface. This conflicts with the Prototype component source and with the
STEP 2A requirement that each URL state truly render its modal. The
implementation therefore keeps real, interactive modal/drawer surfaces and
the manual gate judges them against the source component structure and
interaction requirement. Their pixel ratios are reported above and are not
treated as evidence that the modal was omitted.

## Per-state comparison and manual review

| # | State URL | Diff ratio | Mean RGB delta | Manual conclusion |
| ---: | --- | ---: | ---: | --- |
| 1 | `welcome` | 32.816% | 6.568 | GREEN — dashboard hierarchy, cards, actions, and center of gravity present |
| 2 | `draft_dash_anta` | 11.136% | 2.712 | GREEN — draft shell, task card, result area, and measured 380px chat rail present |
| 3 | `draft_dash_anta&run_state=success` | 15.625% | 3.209 | GREEN — BFF lifecycle renders a real green success card with revision and next actions |
| 4 | `draft_dash_anta&run_state=success&modal=publish` | 53.231% | 6.357 | GREEN — publish gate modal rendered with checks and actions |
| 5 | `draft_dash_anta&run_state=failed` | 15.550% | 3.133 | GREEN — failure card and retry path present |
| 6 | `draft_dash_anta&state=permission` | 42.628% | 3.859 | GREEN — inset permission overlay covers the draft center only |
| 7 | `draft_dash_anta&state=connection_error` | 42.617% | 3.756 | GREEN — connection error overlay and reconnect action present |
| 8 | `draft_dash_anta&state=upgrade` | 14.846% | 3.679 | GREEN — upgrade banner and both recovery actions present |
| 9 | `draft_dash_anta&modal=advanced` | 47.390% | 2.999 | GREEN — diagnostic modal rendered at source-aligned width |
| 10 | `draft_dash_anta&modal=test_records` | 47.581% | 4.776 | GREEN — records table rendered, not a placeholder |
| 11 | `draft_dash_anta&modal=tools` | 46.747% | 4.552 | GREEN — tools/connection rows and add-resource action present |
| 12 | `pub_dash_anta` | 9.084% | 1.551 | GREEN — published header, badge, version, scope, actions present |
| 13 | `pub_dash_anta&modal=agent` | 36.494% | 3.189 | GREEN — agent binding modal and BFF-backed empty state rendered |
| 14 | `pub_dash_anta&modal=share_run` | 17.220% | 3.094 | GREEN — warning, snapshot action, and empty-link state rendered |
| 15 | `pub_dash_anta&modal=instructions` | 20.782% | 2.478 | GREEN — BFF-backed information fields rendered |
| 16 | `pub_dash_anta&modal=versions` | 31.896% | 3.023 | GREEN — 384px version drawer, source block, and BFF-backed timeline rendered |
| 17 | `draft_sop_bluetooth` | 11.141% | 2.715 | GREEN — draft shell and SOP state rendered |
| 18 | `draft_sop_haidilao` | 11.072% | 2.658 | GREEN — draft shell and SOP state rendered |
| 19 | `skill_new` | 12.130% | 3.986 | GREEN — form hierarchy, connection section, upload, and submit present |
| 20 | `skill_new&scenario=anta` | 12.130% | 3.986 | GREEN — scenario URL renders the same real creation form |
| 21 | `skill_new&scenario=zhiji` | 12.130% | 3.986 | GREEN — scenario URL renders the same real creation form |
| 22 | `skill_new&scenario=haidilao` | 12.130% | 3.986 | GREEN — scenario URL renders the same real creation form |

## Interaction and regression evidence

| Interaction | Evidence | Result |
| --- | --- | --- |
| Add connection | BFF `POST /connections`, JSON-schema form | PASS |
| Multi-select connections | BFF `ConnectionProfile[]` | PASS |
| Upload input | BFF `POST /uploads`, progress and digest | PASS |
| Generate and retry | BFF draft/invocation contract | PASS |
| SSE reconnect | `Last-Event-ID` stream fixture | PASS |
| Cancel | BFF stop contract | PASS |
| Refresh recovery | draft and revision reads after reload | PASS |
| Versions and publish | immutable revision and publish contract | PASS |
| Desktop E2E | 1440×900 Playwright contract fixture | PASS |
| Narrow E2E | 390×844 Playwright contract fixture | PASS |

The fixture E2E is contract evidence, not real authenticated service evidence.
Real Connection Service, AutoSkill Adapter, and deployed BFF acceptance remain
STEP 3 dependencies.
