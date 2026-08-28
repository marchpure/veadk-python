# Knowledge Workspace V1 — STEP 2A Visual Capture Report

## Evidence and method

The test-only capture fixture
`frontend/src/features/knowledge-workspace/test-fixtures/captures.ts` records
the 22 Prototype state URLs. The capture harness
`frontend/tests/knowledgeWorkspaceCapture.mjs` renders each state through the
same-origin BFF contract fixture, waits for route content to settle, asserts
the required DOM/page/modal geometry, captures at 1920×1080, and compares the
implementation PNG with the independently downloaded, SHA-verified Prototype
reference using RGB per-pixel absolute delta. The reference directory is
separate from the implementation output directory.

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
responsive behavior. The report was regenerated after restoring the source
aligned VersionHistory Drawer.

Manual review and render-gate result: P0 = 0, P1 = 0. All 22 states render the intended page
or modal rather than a URL-only placeholder. No state has an empty replacement
page, main/right-pane overlap, clipping, or blocking overflow at the reviewed
desktop and narrow layouts. The shared modal surfaces use the Prototype
overlay, header/body/footer, double-column Agent layout, and right-docked
384px full-height version Drawer geometry while retaining BFF-backed content.

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
| Draft advanced / test records / tools | 3 | 46.06–48.65% | 2.08–3.03 | GREEN |
| Draft publish gate | 1 | 49.41% | 4.54 | GREEN |
| Published base | 1 | 9.58% | 1.64 | GREEN |
| Published agent / share / instructions / versions | 4 | 92.35–98.26% | 70.62–81.82 | GREEN* |
| Skill-new and scenarios | 4 | 12.13% | 3.99 | GREEN |

*The four published-modal reference PNGs are published-shell captures without
their URL-requested modal surface. The implementation keeps the required real
modal surfaces, so these ratios are reference anomalies rather than a reason to
remove the modal. The same behavior is reproducible against the hosted
Prototype URLs: HTTP 200, but zero visible `role=dialog` elements for all four
modal query states.

### Published modal reference note

The four Prototype PNGs for `modal=agent`, `modal=share_run`,
`modal=instructions`, and `modal=versions` were captured as mostly the
published base shell and do not visibly contain the corresponding modal
surface. This conflicts with the Prototype component source and with the
STEP 2A requirement that each URL state truly render its modal. The
implementation therefore keeps real, interactive modal surfaces and the
manual gate judges them against the source component structure and interaction
requirement. `versions` is a right-docked 384px full-height Drawer, matching the
source `VersionHistoryModal`. Their pixel
ratios are reported above and are not treated as evidence that the modal was
omitted.

The implementation geometry is source-aligned: the published Agent modal is
896px wide, while the Versions surface is a right-docked 384px full-height
Drawer. From the published page, the real Share Run, Instructions, and Version
History surfaces can each be opened by their corresponding user action; direct
URL states exercise the same mounted components. The four reference PNGs remain
shell-only anomalies, not implementation targets.

## Per-state comparison and manual review

| # | State URL | Diff ratio | Mean RGB delta | Manual conclusion |
| ---: | --- | ---: | ---: | --- |
| 1 | `welcome` | 32.816% | 6.568 | GREEN — dashboard hierarchy, cards, actions, and center of gravity present |
| 2 | `draft_dash_anta` | 11.136% | 2.712 | GREEN — draft shell, task card, result area, and measured 380px chat rail present |
| 3 | `draft_dash_anta&run_state=success` | 15.625% | 3.209 | GREEN — BFF lifecycle renders a real green success card with revision and next actions |
| 4 | `draft_dash_anta&run_state=success&modal=publish` | 49.408% | 4.544 | GREEN — publish gate modal rendered with checks and actions |
| 5 | `draft_dash_anta&run_state=failed` | 15.550% | 3.133 | GREEN — failure card and retry path present |
| 6 | `draft_dash_anta&state=permission` | 42.628% | 3.859 | GREEN — inset permission overlay covers the draft center only |
| 7 | `draft_dash_anta&state=connection_error` | 42.617% | 3.756 | GREEN — connection error overlay and reconnect action present |
| 8 | `draft_dash_anta&state=upgrade` | 14.846% | 3.679 | GREEN — upgrade banner and both recovery actions present |
| 9 | `draft_dash_anta&modal=advanced` | 46.064% | 2.079 | GREEN — diagnostic modal rendered at source-aligned width |
| 10 | `draft_dash_anta&modal=test_records` | 48.645% | 3.031 | GREEN — records table rendered, not a placeholder |
| 11 | `draft_dash_anta&modal=tools` | 46.541% | 2.384 | GREEN — tools/connection rows and add-resource action present |
| 12 | `pub_dash_anta` | 9.581% | 1.639 | GREEN — published header, badge, version, scope, actions present |
| 13 | `pub_dash_anta&modal=agent` | 95.228% | 70.618 | GREEN* — real 896px double-column Agent modal and BFF-backed empty state rendered |
| 14 | `pub_dash_anta&modal=share_run` | 96.266% | 81.817 | GREEN* — real warning, snapshot action, and empty-link state rendered |
| 15 | `pub_dash_anta&modal=instructions` | 92.350% | 75.405 | GREEN* — real BFF-backed information fields rendered |
| 16 | `pub_dash_anta&modal=versions` | 99.356% | 73.377 | GREEN* — real right-docked 384px full-height source-aligned Drawer, source block, and BFF-backed timeline rendered |
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
| Published Share Run / Instructions / Versions | real published-page click targets open the corresponding modal or Drawer | PASS |
| Desktop E2E | 1440×900 Playwright contract fixture | PASS |
| Narrow E2E | 390×844 Playwright contract fixture | PASS |

The fixture E2E is contract evidence, not real authenticated service evidence.
The published Agent picker is intentionally empty because the current
same-origin Knowledge BFF contract exposes no Agent directory endpoint; adding
Prototype demo Agents to production would violate the fixture-only demo-data
boundary. Real Connection Service, AutoSkill Adapter, Agent directory, and
deployed BFF acceptance remain STEP 3 dependencies.
