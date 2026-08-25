# STEP3B W4 v2.15.2 correction evidence

Session: `01a038c9-c29d-7e73-93dc-9bb67813ded0`  
Worktree: `/Users/bytedance/.codex/worktrees/knowledge-step3b-w4-v2152-workspace`  
Branch: `feat/knowledge-step3b-v2152-workspace`  
Base: `1411d706825546e3aba465d95f468a2729ddf8bb`

## Scope completed

- Kept a single workspace shell and normalized legacy `view=skill` deep links into the shared workspace route while preserving `skillId` and `revision`.
- Removed the user-editable fake multi-stage pipeline from the main Skill Builder journey. `BuildPlan` is server-owned and shown only as collapsed/audit progress.
- Replaced production SOP and Monitoring screens with typed ViewModel-gated renderers.
- Kept Dashboard, Semantic, SOP, Knowledge Base, Graph, and Monitoring as Skill visual forms, not peer final products.
- Cleared production default state that previously came from `sample_data`, `dataset_mock_upload`, local demo state, fixed route ids, and URL-driven fake success.
- Preserved the 15-state v2.15.2 acceptance matrix only as test/evidence fixture data.

## Removed fake data and fake-success paths

- `SkillSOPView.tsx`: removed fixed Bluetooth/Haidilao/LS model/SOP/diagnostic facts and fixed result recommendations from production rendering.
- `SkillMonitoringView.tsx`: removed fixed invocation counts, success rate, latency, trace records, alert results, and fixed Skill names from production rendering.
- `ChatAssistant.tsx`: removed fake editable artifact pipeline controls, fixed assistant/tool progress arrays, and timer-simulated Agent streaming.
- `FileTreePane.tsx` and `WorkspaceLayout.tsx`: removed `new_publish` route-driven success highlight, demo reset actions, `sample_data_added`, and `dataset_mock_upload`.
- `dragStore.ts` / drag callers: removed `status: "success"` as a local production success signal.
- `frozen-ui/lib/store.ts` and `frozen-ui/data/mockData.ts`: removed local fixture-backed production defaults and localStorage demo persistence.
- `AddDataView.tsx`: removed hardcoded connector discovery success messages.
- `production/store.ts`: removed `CAPABILITY_MATRIX_ROUTE_IDS` from production route availability; unknown deep links now show a gated route state.
- `domainClient.ts`: removed `Math.random()` fallback id generation.
- Publication/edit/evaluate/sync controls now dispatch typed commands or fail closed/disabled; no Toast is used as proof of backend success.

## Test commands and results

```bash
node --test frontend/tests/knowledgeWorkspaceV2152Shell.test.mjs frontend/tests/knowledgeShellState.test.mjs frontend/tests/knowledgeWorkspaceV21141Contracts.test.mjs frontend/tests/knowledge-workspace-v21141/contracts.test.mjs frontend/tests/knowledge-workspace-v21141/trustedHtmlArtifactRenderer.test.mjs frontend/tests/knowledge-workspace-v21141/productionBoundary.test.mjs
```

Result: `118 passed`.

```bash
cd frontend && npx tsc --noEmit --noUnusedLocals false --noUnusedParameters false --pretty false
```

Result: passed.

```bash
cd frontend && npm test
```

Result: `867 passed`.

```bash
pytest -q tests/frontend/knowledge_workspace_v21141 tests/frontend/test_knowledge_asset_bff.py tests/frontend/test_knowledge_web_import.py tests/frontend/test_knowledge_uploads.py
```

Result: `290 passed, 13 skipped`.

```bash
cd frontend && npm run build
```

Result: passed. Existing Vite warnings remained:

- dynamic imports also statically imported for `src/adk/client.ts`, `src/ui/CodeEditor.tsx`, and `src/adk/connections.ts`;
- several chunks exceed 500 kB after minification.

Generated `veadk/webui` build output was restored/cleaned and is not part of the W4 commit.

## Static production-boundary scans

```bash
rg -n -e '蓝牙诊断信号 API' -e '蓝牙异常排查手册' -e '蓝牙断连排查 SOP' -e '海底捞卫生巡检 SOP' -e '门店卫生巡检与处置 SOP' -e 'LS6' -e 'LS7' -e 'OS-2\.1\.0' -e 'V1\.2\.4' -e '-85dBm' -e '-92dBm' -e '12 条历史工单' -e '1,245' -e '98\.2%' -e '1\.4s' -e 'tr_89112' -e 'sample_data_added' -e 'dataset_mock_upload' -e '使用示例数据' -e '演示数据' -e 'new_publish' -e 'dragStore\.setState\(\{ status: .success' -e "setRunState\([\"']result[\"']\)" -e "localStorage\.(setItem|getItem|removeItem|clear)\(\s*[\"']demo_" -e 'setTimeout\([\s\S]{0,160}(thinking|tool|progress|执行完成|生成完成|成功)' -e 'Math\.random\(' frontend/src/knowledge-workspace tests/fixtures/knowledge_step3b_w4_v2152 --glob '!frozen-ui/prototype-route.json' --glob '!production/generatedContracts/**' --glob '!production/generatedContracts.ts'
```

Result: no matches (`rg` exit code 1 with empty output).

```bash
rg -n -e '蓝牙' -e '海底捞' -e '卫生巡检' -e '断连' -e 'LS6' -e 'LS7' -e 'OS-2' -e '固件' -e 'dBm' -e '历史工单' -e '1,245' -e '98\.2' -e '1\.4s' -e 'tr_' frontend/src/knowledge-workspace tests/fixtures/knowledge_step3b_w4_v2152 --glob '!frozen-ui/prototype-route.json' --glob '!production/generatedContracts/**' --glob '!production/generatedContracts.ts'
```

Result: no matches (`rg` exit code 1 with empty output).

## 15-state acceptance

- Fixture: `tests/fixtures/knowledge_step3b_w4_v2152/captures.json`.
- Contains exactly 15 route states.
- Fixture is test/evidence-only; production routing no longer whitelists these route ids.
- Covered by `knowledgeWorkspaceV2152Shell.test.mjs`:
  - validates the 15-state fixture shape;
  - validates no listed business facts leak into SOP/Monitoring production views;
  - validates fixture route ids do not leak into production routing or state.

## MAIN typed seams needed

- Workspace bootstrap should declare canonical routes/resources with `resourceKind`, `subtype`, `skillId`, `draftId`, `revision`, and `view_revision_id` where applicable.
- Source/golden connectors, MCP profiles, files, knowledge bases, and API resources should be returned as typed context refs that can be attached to Agent authoring.
- Policy gate and publication status should refresh from server after `policy-gate.evaluate` and `publication.publish`.
- Published Skill monitoring should return typed `Invocation`/`Operation`/trace/freshness/failure records rather than front-end inferred status.

## W2 dependency proposal

- Right Agent panel consumes real `skill-authoring.*` command results and operation ids. W2 should provide the streaming/timeline contract for:
  - assistant delta;
  - tool call;
  - plan summary;
  - context/revision;
  - warning/error;
  - stop/retry/resume.
- `skill-draft.run` should accept/return a typed Runner input reference and produce operation events plus immutable `SkillViewRevision`.
- UI must not expose chain-of-thought, system prompts, secrets, or raw sensitive tool output; event payloads should already be redacted/typed.

## W3 dependency proposal

- Generate canonical ViewModel contracts for:
  - `DashboardViewModel`;
  - `SemanticViewModel`;
  - `SopViewModel`;
  - `GraphOntologyViewModel`;
  - `MonitoringViewModel`;
  - immutable `SkillViewRevision` / trusted HTML revision.
- Register template/kind runtime mappings so Dashboard, Semantic, SOP, Knowledge Graph, Knowledge Base, Monitoring, and generic HTML are all Skill visualization templates.
- `SopViewModel` is currently a minimal local W4 UI seam and should be replaced by the generated W3 contract when available.

## Caveats

- `frontend/SPEC.md` references `../.agents/skills/frontend-design/SKILL.md` and `../.agents/skills/ui-ux-pro-max/SKILL.md`; both files were absent in this checkout, so W4 used `frontend/SPEC.md` and existing workspace components as the binding design source.
- Strict `cd frontend && npx tsc --noEmit --pretty false` still fails on existing `noUnused*` noise across frozen UI and generated contract bundle files. The practical frontend type gate with `noUnusedLocals` and `noUnusedParameters` disabled passes, and the production build passes.
- No browser screenshot/HAR/video artifacts were generated in this W4 correction. The 15-state acceptance is represented as JSON fixture plus Node boundary tests.
