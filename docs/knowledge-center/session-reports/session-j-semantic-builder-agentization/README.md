# Session J Semantic Builder Agentization

## Scope

- Branch: `kc/session-j-semantic-builder-agentization`
- Remote: `origin https://github.com/marchpure/veadk-python.git`
- Start hash: `9d982aa1708ace7f3f16b5b19d8b7ae1c5fb5f32`
- End hash: recorded by the commit that includes this report.

Session J replaces the previous Knowledge Asset semantic builder path with a native AgentKit Studio Semantic Builder Workbench. The flow stays inside Studio, without BYAAN iframe or local product shell dependencies, and produces governed Semantic Skill assets with auditable build events, Wren-style MDL artifacts, Semantica-style document graph evidence, editable few-shot/instruction memory, and publish gates.

## Implementation Summary

- Added `SemanticBuilderAgent`, an internal `veadk.Agent`/`Runner` backed builder that streams auditable tool events and records persisted job events.
- Added build-job event storage and API access for semantic build replay/resume.
- Extended the Knowledge Asset store with semantic few-shot SQL pairs, semantic instructions, graph objects, graph relations, and doc-to-MDL alignments.
- Added fail-closed publish gating: a model-unconfigured run can create a draft/preview pack but cannot report published success.
- Added source sanitization and redaction on source metadata, document context, job input/output, events, generated packages, and report artifacts.
- Reworked the Knowledge Center semantic UI into a native Studio workbench with streamed agent progress, Wren-inspired modeling canvas, evidence/alignment inspection, MDL/raw panes, and responsive mobile metadata panes.
- Integrated the Wren source-port UI as native React components rather than an iframe shell, preserving Studio layout and mobile overflow constraints.
- Regenerated tracked `veadk/webui` static assets from the production frontend build.

## API Surface

- `POST /api/knowledge-assets/build/semantic-skill`: enqueue background Semantic Skill build.
- `POST /api/knowledge-assets/semantic-build/stream`: start a Semantic Skill build and stream Server-Sent Events.
- `GET /api/knowledge-assets/semantic-build/{job_id}/events`: read persisted semantic build events after a sequence.
- `GET /api/knowledge-assets/semantic/question-sql-pairs`, `POST`, `PATCH`, `DELETE`: manage few-shot question/SQL examples.
- `GET /api/knowledge-assets/semantic/instructions`, `POST`, `PATCH`, `DELETE`: manage semantic builder instructions.
- `GET /api/knowledge-assets/semantic/graph-objects`, `PATCH`: review graph concepts.
- `GET /api/knowledge-assets/semantic/graph-relations`, `PATCH`: review graph relations.
- `GET /api/knowledge-assets/semantic/alignments`, `PATCH`: review doc-to-MDL alignments.
- `GET /api/knowledge-assets/semantic-packs/{asset_id}/detail`: load packaged MDL, evidence, graph, alignments, few-shot examples, instructions, and runtime query metadata.
- `POST /api/external/assets/semantic_model/{asset_id}/query`: governed query adapter for published Semantic Skills.

## Semantic Builder Agent Toolchain

`studio_semantic_builder_agent` exposes and audits these tool steps:

- `inspect_schema_snapshot`
- `load_document_context`
- `extract_semantica_graph`
- `build_schema_graph`
- `propose_wren_mdl`
- `align_docs_to_mdl`
- `validate_semantic_pack`
- `save_semantic_pack`
- `publish_semantic_skill`

The E2E run confirmed the runtime health path reported `runner_backend: veadk.Agent+Runner`, `configured: true`, and deterministic fallback disabled for the semantic builder.

## WrenAI Migration Points

- MDL generation now emits models, fields, relationships, metrics, dimensions, permissions, freshness, and evidence files under a Semantic Skill package.
- The UI provides Wren-style modeling inspection through native React panels: schema graph, model list, MDL/raw view, and source inspector evidence.
- The published asset query URL is a governed Studio route, not a database connection or raw SQL fallback.
- Runtime package files include a governed REST tool stub and policy files instead of direct Oracle or source credentials.

## Semantica Migration Points

- Document sources are converted into semantic graph objects and relations.
- Graph-to-MDL alignments are persisted and reviewable.
- Few-shot question/SQL examples and builder instructions are stored as first-class semantic memory.
- The semantic pack detail endpoint consolidates MDL, doc graph, alignments, evidence, few-shot examples, and runtime status for the workbench.

## Validation

- `cd frontend && npm test`
  - Passed: `679` tests, `0` failures.
- `cd frontend && npm run build`
  - Passed. Vite emitted existing chunk-size/dynamic-import warnings and regenerated tracked `veadk/webui` assets.
- `cd frontend && node --test tests/semanticBuildPanel.test.mjs tests/knowledgeAssetWorkbench.test.mjs`
  - Passed: `13` tests, `0` failures.
- `pytest -q tests/frontend/test_knowledge_asset_store.py tests/frontend/test_knowledge_asset_semantic_builder.py tests/frontend/test_semantic_builder.py`
  - Passed: `27` tests, `0` failures.
- `python -m compileall frontend/server/knowledge_assets tests/frontend docs/knowledge-center/session-reports/session-j-semantic-builder-agentization/e2e_semantic_builder.py`
  - Passed.
- `uvx ruff@0.11.12 check frontend/server/knowledge_assets/agents/semantic_builder.py frontend/server/knowledge_assets/models.py frontend/server/knowledge_assets/repository.py frontend/server/knowledge_assets/routes.py frontend/server/knowledge_assets/service.py tests/frontend/test_knowledge_asset_store.py tests/frontend/test_knowledge_asset_semantic_builder.py tests/frontend/test_semantic_builder.py docs/knowledge-center/session-reports/session-j-semantic-builder-agentization/e2e_semantic_builder.py`
  - Passed.
- `npx pyright --pythonpath "$(which python)" frontend/server/knowledge_assets/agents/semantic_builder.py frontend/server/knowledge_assets/models.py frontend/server/knowledge_assets/repository.py frontend/server/knowledge_assets/routes.py frontend/server/knowledge_assets/service.py tests/frontend/test_knowledge_asset_store.py tests/frontend/test_knowledge_asset_semantic_builder.py tests/frontend/test_semantic_builder.py docs/knowledge-center/session-reports/session-j-semantic-builder-agentization/e2e_semantic_builder.py`
  - Passed: `0` errors, `0` warnings.
- `uvx --from pre-commit pre-commit run gitleaks --files ...`
  - Passed on changed source, tests, report, and web index files.
- Focused ripgrep secret scan:
  - Findings are expected credential-handling code and synthetic redaction fixtures such as `must-not-leak`, `redact-me-*`, and `unit-test-model-key`.
  - No real plaintext secret was found in changed source, tests, result JSON, report assets, or web index.

## Playwright E2E

Command:

```bash
python docs/knowledge-center/session-reports/session-j-semantic-builder-agentization/e2e_semantic_builder.py
```

Result file: `docs/knowledge-center/session-reports/session-j-semantic-builder-agentization/result.json`

- Passed: `true`
- Duration: `5.75s`
- Backend: `http://127.0.0.1:8000`
- Semantic builder health: configured, `veadk.Agent+Runner`, model `doubao-seed-2-0-lite-260428`
- Latest job: `succeeded`
- Publish state: `published`
- Persisted event count: `31`
- Persisted detail: `few_shot: 1`, `instructions: 1`, `graph_objects: 7`, `graph_relations: 1`, `alignments: 4`
- Mobile horizontal overflow: `0px`

Screenshots:

- `screenshots/desktop-modeling-workbench.png` (`1440x900`)
- `screenshots/desktop-evidence-alignments.png` (`1440x900`)
- `screenshots/mobile-metadata-pane.png` (`390x844`)

## Known Limits And Next Steps

- The builder requires a configured model before publishing; unconfigured runs intentionally remain draft/blocked.
- Chunk-size warnings remain from the existing frontend build and were not introduced as a functional blocker in this session.
- Cross-source WrenAI/Semantica reconciliation is currently evidence-based and deterministic around available snapshots/documents; deeper live database profiling remains out of scope for the native workbench path.
