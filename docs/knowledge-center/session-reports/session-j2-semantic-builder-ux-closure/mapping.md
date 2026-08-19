# Session J2 Semantic Builder Mapping

| Source / concept | AgentKit implementation | Notes |
| --- | --- | --- |
| WrenAI `modeling.tsx` `SiderLayout` with model tree, central `Diagram`, and `MetadataDrawer` | `SemanticBuildPanel.tsx` now renders one Wren-source-port workspace through `WrenModelingSourcePort`; `KnowledgeCenter.tsx` no longer stacks the old builder plus modeling workbench. | Ported information architecture, not Wren runtime. |
| WrenAI diagram components (`components/diagram`, Model/View nodes, relationship edges) | Existing `source-ports/wren/original/diagram` remains the primary canvas inside `WrenModelingSourcePort`. | Direct structure/style port; no iframe, Apollo, Next router, or Wren service dependency. |
| WrenAI `ModelDrawer`, `RelationModal`, calculated field flows | `WrenModelingSourcePort` exposes `New Model`, `Relationship`, `Metric`, `Edit`, disabled `Publish`, and `Run Eval` handlers with real feedback/disabled reasons. | Local draft editing is preserved; persistence remains through Semantic Builder regeneration and quality gate. |
| WrenAI `QuestionSQLPairModal` and `InstructionModal` | `TrainingDrawer` provides `Training Examples` and `Governance Rules` forms with create/update/delete calls to existing semantic pair/instruction endpoints. | Moved out of first screen; persists and survives refresh. |
| WrenAI deploy/build status strip | Compact status chips show build, agent, runner, generation mode, drafts, and publish state below the modeling action bar. | Top builder bar keeps only skill, data context, generate, and state. |
| Semantica context graph | `Evidence` inspector reads `doc_graph` entities, relations, and evidence fragments from persisted Semantic Pack detail. | Local Semantica source was found under `/Users/bytedance/semantica`; mapping follows its graph-to-ontology lifecycle. |
| Semantica ontology candidates | `Evidence` inspector includes `Ontology Candidates`; run details stage includes `Propose ontology`. | Inspired by Semantica ontology generator stages: semantic network parsing, class/property inference, hierarchy, validation. |
| Semantica provenance / alignment | `Evidence` inspector shows `Provenance` and `Alignments`; run details includes `Link evidence`. | Backed by persisted `doc_graph`, `alignments`, and asset provenance from `/api/knowledge-assets/semantic-packs/{id}/detail`. |
| Semantica validation gate | `Evals` inspector shows validation gate and eval seed; run details includes `Validate SQL`. | Keeps validation out of canvas while visible in inspector. |
| Old J `Data Scope`, few-shot, instructions, transcript, artifact cards, readiness rail | Replaced by compact `DataContextSelector`, right inspector tabs, and drawers for run/training. | Removed from first screen; no long debug-stack page. |
| Old duplicate Semantic Skill cards | Semantic skill selector/tree now dedupes same name/version entries. | Default view shows current skill’s model tree, not repeated cards. |
