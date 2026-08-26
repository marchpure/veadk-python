# STEP3B Worker 3 evidence

Date: 2026-08-25

## Visual correction supplement

This correction replaces the single fixed light-card presentation with a
direction-aware compiler pipeline:

```text
TemplateSpec → DesignDirection → DesignTokens → PresentationRecipe
→ typed ViewModel → HTMLCompiler → VisualEvaluator → immutable HTML revision
```

`design_system.py` defines five directions (`editorial`, `executive`,
`analytical`, `operational`, `compact`) and token contracts for typography,
spacing, radius, surface hierarchy, semantic states, chart palette, table
density and focus/hover/selected/disabled/error/stale states. `template.html`
and `visual-profile.json` are now explicit bundle contracts; the compiler
consumes the direction and emits it in the immutable HTML metadata.

The six presenters now use typed content to choose modules:

- Dashboard supports typed line/bar/stacked-bar/area chart declarations,
  three KPI cards, filters, drill, export/citation events, insights and
  freshness/state coverage.
- Semantic has entity selection, field catalog, relationship SVG canvas,
  join evidence, context action and MDL disclosure.
- SOP has run state, branch/tool/input summaries, run/retry/evidence events,
  and an explicit confirmation safety boundary.
- Knowledge has a five-source citation rail, search/add-context actions and
  access boundary.
- Graph/Ontology acceptance fixtures contain 12 nodes and 15 edges with
  confidence/evidence; the page has topology, legend, selected detail and
  conflict panel.
- Monitoring has call volume, success rate, latency, stale/alert state,
  observations, trend, alerts and trace action.

`compile_with_visual_feedback` evaluates every candidate on ten dimensions,
records score/reasons, and revises the direction at most three rounds. It
never lowers the 4/5 core threshold or writes a score into the artifact.

The acceptance harness now generates two structurally different fixture sets
(operations trend / warehouse capacity, plus corresponding semantic/SOP/
knowledge/graph/monitoring variants). Playwright audited 36 screenshots:
6 templates × 2 business structures × 3 viewports
(1440×900, 1024×768, 390×844). All passed no horizontal overflow, console
errors, scripts, iframes or external requests. Scores and round choices are
in `/tmp/veadk-w3-html-acceptance-v3/visual-evaluation.json`; screenshots and
browser facts are in `/tmp/veadk-w3-html-evidence-v3`.

Reference code evidence used:

- html-anything `next/src/lib/templates/index.ts` and
  `next/src/lib/skills/registry.ts`: folder-discovered template protocol,
  example artifact and skill metadata separation.
- Open Design `docs/skills-contributing.md`, `craft/state-coverage.md` and
  `craft/anti-ai-slop.md`: hand-built examples, DESIGN/SKILL/checklist
  discipline, explicit state coverage and anti-placeholder rules.
- Byaan `client/src/pages/ChatPreview.tsx`: dashboard preview/version/filter
  coordination and inspectable code/preview workflow.

Known gaps versus the references: the acceptance harness is a local static
site rather than the full W4 Shell; event handling and backend refresh remain
outside this W3 scope; there is no pixel-level visual diff against Byaan's
proprietary production data, and the server-side SVG graph uses deterministic
layout rather than a full graph-layout engine.

## HTML compiler supplement

The formal HTML path is now a versioned `TemplateBundle` plus deterministic
`PresentationRecipe` and `HTMLCompiler`, not JSON wrapped in a page. Each of
the six bundles under `frontend/server/knowledge_assets/template_bundles/`
contains `SKILL.md`, `DESIGN.md`, `template.html`, `example.html`,
`checklist.md`, and `manifest.json`.

Dashboard, Semantic, SOP, Knowledge, Graph/Ontology, and Monitoring each have
their own information architecture. Charts and graph topology are server
generated SVG; controls are declarative `data-artifact-event` attributes.
Every document carries template/version, ViewModel digest, data revisions,
renderer version and CSP. No formal output contains a script, iframe, external
request or primary JSON `<pre>`.

The independent harness and browser audit are:

```text
python -m frontend.server.knowledge_assets.html_acceptance \
  --output /tmp/veadk-w3-html-acceptance-v3
node tools/skill_html_visual_audit.mjs \
  /tmp/veadk-w3-html-acceptance-v3 /tmp/veadk-w3-html-evidence-v3
```

The audit produced 36 screenshots (six templates × two structurally different
fixtures × 1440×900, 1024×768 and 390×844). All passed: no horizontal
overflow, console errors, scripts, iframes or external requests. Each browser
record includes the declarative event type set, direction, visual profile,
score and bounded visual attempts. Final scores are 4.67/5.00 for every
template/scenario and every attempt has `corePass=true`. Evidence remains
outside the repository at `/tmp/veadk-w3-html-evidence-v3`; acceptance
metadata is at `/tmp/veadk-w3-html-acceptance-v3/visual-evaluation.json`.

## Automated evidence

`test_step3b_templates_sop.py` proves:

- six built-in TemplateSpecs plus durable workspace-scoped copy/version/spec.md;
- explicit TemplateRef and immutable context revision binding;
- two independent Dashboard workspaces with different source fields and
  values: regional revenue (`340`, `region`) and warehouse inventory (`26`,
  `warehouse`); titles, KPI, chart series, table fields, and HTML digests differ;
- Semantic Skill revision composition and typed schema-drift rejection;
- IM Bluetooth and Haidilao hygiene SOPs with different schemas, steps, tools,
  evidence and outcomes; write-risk steps produce confirmation proposals only;
- typed conversational patch creates revision 2 for Dashboard and SOP, and
  Graph entities/relationships project from the changed typed spec;
- cross-workspace Golden Asset execution is denied;
- HTML contains CSP and no `script` or `iframe`.

Existing suites additionally prove Knowledge retrieval/citation/refusal,
Semantic discovery/MDL/ambiguity/dependency errors, Graph mapping evidence,
Monitoring observation/alert/last-good/failure lifecycle, immutable view
persistence, evaluation policy gates, publishing, and published invocation
from a new caller session.

## Commands

```text
pytest -q tests/frontend/knowledge_workspace_v21141 tests/frontend/test_knowledge_asset_bff.py
202 passed, 13 skipped

pytest -q tests/frontend/knowledge_workspace_v21141/test_skill_html_compiler.py
6 passed

npm run build
passed (production Vite build; existing chunk-size/dynamic-import warnings only)

pre-commit run --files ...
passed (ruff check, ruff format, secret scan)
```

The skipped cases are environment-dependent external/browser cases already
marked by the baseline suite, not STEP3B assertions.

Generated JSON Schema and TypeScript contracts were validated locally with:

```text
python -m frontend.server.knowledge_assets.schema_export
```

The generated schema and TypeScript changes are retained in this W3 commit:
they were regenerated from the current typed contracts with
`python -m frontend.server.knowledge_assets.schema_export` and verified by the
full test/build run. Integration MAIN still owns any subsequent shared-client
coordination.

Prototype archive SHA-256 was independently verified as:

```text
0a672e34dd8f5cf416a73334b519679ee756f2c50ea8710166dae4b6b6c41b15
```

No runtime evidence, SQLite database, downloaded prototype, or HTML capture is
committed.
