# STEP 3 v2.13.1 UI Delta

Date: 2026-08-25
Prototype archive SHA-256: `ce6e086b806072c363f23ed68c9e067b30b280738af0284eeb60ca36c22e5571`

## Measured baseline

- Frozen repository UI: 48 TypeScript/TSX files, 9,388 lines.
- v2.13.1 prototype source: 49 files, 9,864 lines (48 TypeScript/TSX
  implementation files plus the route manifest).
- Prototype route manifest: 43 states.
- Frozen complete route manifest: 23 states.
- Route relationship: all 23 frozen states are retained in the 43-state
  prototype manifest; 20 states are added.
- Source comparison against `frontend/src/knowledge-workspace/frozen-ui`:
  11 changed paths, `+620/-77`, net `+543` lines. The 11 paths are the
  nine changed existing source paths plus the two new prototype components.
  The objective's approximate `+620/-79` includes export/newline accounting
  from the prototype packaging.

## Path-level treatment

| Prototype path | Treatment | Production decision |
|---|---|---|
| `components/Layout/FileTreePane.tsx` | retained and ported | Collapse navigation to Data & Knowledge, Skill Drafts, Published Skills. |
| `components/Layout/MainAreaPane.tsx` | retained and ported | Route the v2.13 states through the existing Studio shell. |
| `components/Layout/TopNav.tsx` | retained and ported | Move acceptance entry under review/more affordance. |
| `components/Layout/WorkspaceLayout.tsx` | retained and ported | Preserve the high-fidelity shell and panes. |
| `components/MainArea/ArtifactHeader.tsx` | retained and ported | Expose debug, evaluation, human share, and Agent handoff actions. |
| `components/MainArea/SkillArtifactView.tsx` | retained and ported | Show server-backed I/O, dependencies, permissions, freshness, evaluation, version, compatibility. |
| `components/RightPane/ChatAssistant.tsx` | retained and ported | Make the home composer explain the real Skill workflow. |
| `lib/store.ts` | retained with production adapter | Keep UI state local; business state comes from the typed BFF/read models. |
| `prototype-route.json` | retained as route contract | Use as the 43-state reachability input and visual/action matrix source. |
| `components/MainArea/JourneyDetailView.tsx` | new, ported selectively | Use the compact three-stage journey shell; keep detailed steps diagnostic. |
| `components/Modals/V212EntryDrawer.tsx` | new, ported selectively | Keep as a review/acceptance entry, not a primary product destination. |

## Reused and rejected prototype behavior

The existing Dashboard, Chart, Semantic, Knowledge Base, Knowledge Graph,
Evaluation, modal, and right-pane components remain the high-fidelity
implementation surface. A second low-fidelity page system is rejected.

Prototype `mockData`, `localStorage`, `setTimeout` animations, fixed scores,
fixed call counts, simulated publish/call success, static schema drift, and
browser-only persistence are rejected as production facts. The production
surface must use the typed BFF, durable operations, read models, real
revisions/results/views/evaluations/traces, or an explicit gated/deferred
state. Formal PublishedSkillVersion, Registry publication, scheduler, and
cross-Agent calling remain STEP 4.

## Route additions

The 20 additions are the v2.12 entry drawer, five journey entry states, five
journey error/build/evaluation states, five journey publish/calling states,
and the five-stage recruitment action-loop views introduced by the exported
route tree. Their exact URLs and owner/status are in
`STEP3_PROTOTYPE_CAPABILITY_MATRIX.yaml` and
`STEP3_V2131_UI_DELTA.json`.

