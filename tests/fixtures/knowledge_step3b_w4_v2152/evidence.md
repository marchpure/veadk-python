# STEP3B W4 v2.15.2 UI correction evidence

Session: `01a038c9-c29d-7e73-93dc-9bb67813ded0`  
Worktree: `/Users/bytedance/.codex/worktrees/knowledge-step3b-w4-v2152-workspace`  
Branch: `feat/knowledge-step3b-v2152-workspace`  
Start HEAD: `6905f074e31a77686e69a0594b35f5ad22ce2ff1`

## Prototype review

- Export unpacked at `/tmp/knowledge-v2152-rerun3.enFUPp`.
- Export SHA-256: `0a672e34dd8f5cf416a73334b519679ee756f2c50ea8710166dae4b6b6c41b15`.
- Reviewed required files:
  - `prototype/readme.md`
  - `prototype/captures.json`
  - `prototype/codebase/src/**`
  - `prototype/notebook/plan-v2.15.md.md`
  - `prototype/notebook/plan-v2.15.1.md.md`
  - `prototype/notebook/plan-v2.15.1-fix.md.md`
- Online prototype returned 404 during evidence capture, so reference screenshots used the `captures.json` TOS PNG fallback.

## Browser evidence

Runtime evidence root: `/Users/bytedance/.codex/runtime/knowledge-step3b-w4-v2152/visual-evidence-final2-20260826010602`

- Report: `report.json`
- Report SHA-256: `f89b7f2e7e34a35bf1815c388bde2df354e4575c587c7fa9e9fb9d2d8abcce5e`
- Status: `pass`
- Screenshots: `45` W4 actual + `45` prototype reference + `45` overlay/diff
- Viewports:
  - `desktop-1920` (`1920×1080`)
  - `studio-1440` (`1440×900`)
  - `mobile-390` (`390×844`)
- Checked for each state:
  - DOM/layout summary
  - console errors
  - failed requests
  - horizontal overflow
  - keyboard navigation
  - modal/drawer obstruction
  - Agent pane collapsed/expanded main-area width
- Failures: `0`
- Home → Builder browser regression: `pass`
  - prompt preserved
  - context refs preserved
  - selected template preserved
  - workspace scope preserved
  - `operation_id` and `draft_id` from typed command preserved
  - reload restores the Builder input

## 15-state acceptance

Fixture: `tests/fixtures/knowledge_step3b_w4_v2152/captures.json`

The browser run covered all 15 prototype states in all three viewports:

1. `home`
2. `agent-clarify`
3. `bluetooth-sop-draft`
4. `edit-sop-step`
5. `bluetooth-sop-input`
6. `bluetooth-sop-result`
7. `publish-to-agent`
8. `anta-dashboard-draft`
9. `anta-dashboard-result`
10. `publish-team`
11. `haidilao-sop-draft`
12. `haidilao-sop-input`
13. `haidilao-sop-result`
14. `published-sop-monitoring`
15. `optimization-draft`

The state names above are fixture/evidence identifiers only. Production routing does not infer business content from these route names.

## Implemented W4 corrections

- Restored the high-density v2.15.2 Home experience:
  - business-problem composer;
  - upload entry;
  - drag/drop resource ingestion gate;
  - `@` search against the bootstrap/read-model catalog;
  - removable context chips with source/revision metadata;
  - template library for Dashboard, Semantic, SOP, Knowledge, Graph/Ontology, Monitoring, and generic HTML Skill;
  - custom `spec.md` preview/reuse/save gates;
  - Agent recommendation and clarification states.
- Reworked Skill Builder away from the user-visible six-step wizard:
  - business material → template/Agent match → clarification → trusted HTML Skill → right-side Agent edits → run/evaluate/publish;
  - Manifest, BuildPlan, trace, and revision details are only in advanced/audit UI;
  - prompt/template/context/workspace handoff survives navigation and reload through URL + server bootstrap authoring-session fields, not localStorage.
- Added unified trusted HTML Skill revision rendering for generated Dashboard/Semantic/SOP/Knowledge/Graph/Monitoring/HTML views.
- Connected visible operations to typed command/read-model seams or fail-closed gates:
  - `skill-authoring.start`
  - `skill-authoring.answer`
  - `skill-authoring.patch`
  - `skill-authoring.execute`
  - `refresh.run`
  - `artifact.export`
  - `evaluation.run`
  - `publication.publish`
  - `invocation.start`
- Reworked the right Agent panel to consume W2 `operation/timeline` streaming events:
  - user message;
  - assistant Markdown delta;
  - current status;
  - tool-call card with name/status/elapsed/summary;
  - context/revision;
  - clarification;
  - warning/error;
  - stop/retry/resume;
  - refresh/interruption recovery display;
  - bottom auto-scroll only when the user has not scrolled away.
- Fixed right-pane open/closed deep-link handling so explicit `pane=closed` is preserved and main content width changes correctly when the Agent pane opens.

## Removed fake data and fake-success paths

- Removed fixed business facts and fixed result recommendations from production SOP rendering:
  - Bluetooth diagnostic API/manual/SOP content;
  - Haidilao inspection SOP content;
  - LS6/LS7, OS/firmware versions, dBm readings, historical ticket counts, and fixed diagnosis/remediation text.
- Removed fixed monitoring metrics and trace records from production Monitoring rendering:
  - fixed invocation count;
  - fixed success rate;
  - fixed latency;
  - fixed trace/call/alarm records;
  - fixed Skill names.
- Removed URL/local-state routes that manufactured success:
  - sample-data added state;
  - mock dataset upload success;
  - route-driven new publication highlight;
  - localStorage demo persistence for production business state;
  - request-complete-to-success-page jumps.
- Removed timer-simulated Agent thinking/tool/progress/success. Remaining timers are limited to UI mechanics such as drag hover reset, toast dismissal, and HTTP timeout/retry.

## Static production-boundary scan commands

Production source scan:

```bash
rg -n -e '蓝牙诊断信号 API' -e '蓝牙异常排查手册' -e '蓝牙断连排查 SOP' -e '海底捞卫生巡检 SOP' -e '门店卫生巡检与处置 SOP' -e 'LS6' -e 'LS7' -e 'OS-2\.1\.0' -e 'V1\.2\.4' -e '\-85dBm' -e '\-92dBm' -e '12 条历史工单' -e '1,245' -e '98\.2%' -e '1\.4s' -e 'tr_89112' -e 'sample_data_added' -e 'dataset_mock_upload' -e '使用示例数据' -e '演示数据' -e 'new_publish' -e 'dragStore\.setState\(\{ status: .success' -e "setRunState\([\"']result[\"']\)" -e "localStorage\.(setItem|getItem|removeItem|clear)\(\s*[\"']demo_" -e 'setTimeout\([\s\S]{0,160}(thinking|tool|progress|执行完成|生成完成|成功)' -e 'Math\.random\(' frontend/src/knowledge-workspace --glob '!frozen-ui/prototype-route.json' --glob '!production/generatedContracts/**' --glob '!production/generatedContracts.ts'
```

Result: no matches.

Broad business-fact scan:

```bash
rg -n -e '蓝牙' -e '海底捞' -e '卫生巡检' -e '断连' -e 'LS6' -e 'LS7' -e 'OS-2' -e '固件' -e 'dBm' -e '历史工单' -e '1,245' -e '98\.2' -e '1\.4s' -e 'tr_' frontend/src/knowledge-workspace --glob '!frozen-ui/prototype-route.json' --glob '!production/generatedContracts/**' --glob '!production/generatedContracts.ts'
```

Result: no matches.

Timer/local state scan:

```bash
rg -n -e 'localStorage' -e 'setTimeout' -e 'setInterval' frontend/src/knowledge-workspace --glob '!frozen-ui/prototype-route.json' --glob '!production/generatedContracts/**' --glob '!production/generatedContracts.ts'
```

Result reviewed:

- `production/adapterChanges.json`: documentation text only.
- `mobile-shell/status-bar.tsx`: clock refresh.
- `production/httpAdapter.ts`: HTTP retry/timeout.
- `WorkspaceLayout.tsx` and `FileTreePane.tsx`: drag hover/reset and toast dismissal.
- No timer-driven streaming, generation completion, or production success state.

## Test commands

Final gate commands for this handoff:

```bash
node --test frontend/tests/knowledgeWorkspaceV2152Shell.test.mjs
node --test frontend/tests/knowledgeWorkspaceV2152Shell.test.mjs frontend/tests/knowledgeShellState.test.mjs frontend/tests/knowledgeWorkspaceV21141Contracts.test.mjs frontend/tests/knowledge-workspace-v21141/contracts.test.mjs frontend/tests/knowledge-workspace-v21141/trustedHtmlArtifactRenderer.test.mjs frontend/tests/knowledge-workspace-v21141/productionBoundary.test.mjs
cd frontend && npm test
cd frontend && npx tsc --noEmit --noUnusedLocals false --noUnusedParameters false --pretty false
cd frontend && npm run build
pytest -q tests/frontend/knowledge_workspace_v21141 tests/frontend/test_knowledge_asset_bff.py tests/frontend/test_knowledge_web_import.py tests/frontend/test_knowledge_uploads.py
KNOWLEDGE_V2152_EVIDENCE_DIR=/Users/bytedance/.codex/runtime/knowledge-step3b-w4-v2152/visual-evidence-final2-20260826010602 node frontend/scripts/knowledge_step3b_w4_v2152_visual_evidence.mjs --prototype-dir /tmp/knowledge-v2152-rerun3.enFUPp
```

Results are recorded in the final W4 handoff after the full gate run.

## MAIN integration seams

- Bootstrap/read model should return typed workspace catalog resources with stable resource ids, revisions, scopes, and server context refs.
- Authoring session bootstrap should return:
  - `draftId`;
  - prompt;
  - selected template/requested kind;
  - context refs;
  - operation id;
  - latest immutable `SkillViewRevision`.
- W2 should provide the streaming timeline events consumed by W4:
  - assistant delta;
  - tool call;
  - plan summary;
  - context/revision;
  - clarification;
  - warning/error;
  - stop/retry/resume.
- W3 should provide canonical generated contracts and trusted renderer registration for:
  - `DashboardViewModel`;
  - `SemanticViewModel`;
  - `SopViewModel`;
  - `GraphViewModel`;
  - `MonitoringViewModel`;
  - immutable `SkillViewRevision` / trusted HTML artifact.

## Notes

- The browser evidence script uses deterministic typed fixtures only inside the test harness.
- The production Shell remains fail-closed when the server does not return the required typed ViewModel/ViewRevision.
- No W1 connector/backend, W2 runtime backend, W3 template registry/runtime, generated contract bundle, or MAIN integration files were modified.
