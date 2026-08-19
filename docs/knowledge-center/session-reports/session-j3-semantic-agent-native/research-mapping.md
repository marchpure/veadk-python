# Session J3 Semantic Builder Agent-Native Closure — Research Mapping

## Scope

Session J3 closes the Semantic Builder loop on top of J2. The target is a real Agent-driven, auditable semantic modeling workspace:

- Start uses structured data sources and optional business documents to create a draft Semantic Skill.
- Refine modifies the current draft through conversation and structured patch, not full rebuild.
- Revision, accept/reject/revert, View draft, and explicit Publish form a complete user loop.
- No configured model fails closed; deterministic fallback is never reported as Agent success.

## AgentKit Studio current flow

Files inspected before implementation:

- `frontend/src/knowledge-center/SemanticBuildPanel.tsx`
- `frontend/src/knowledge-center/SemanticModelingWorkbench.tsx`
- `frontend/src/features/knowledge-assets/source-ports/wren/WrenModelingSourcePort.tsx`
- `frontend/src/features/knowledge-assets/adapters/wrenSemanticAdapter.ts`
- `frontend/server/knowledge_assets/agents/semantic_builder.py`
- `frontend/server/knowledge_assets/agents/runner.py`
- `frontend/server/knowledge_assets/builders/semantic/service.py`
- `frontend/server/knowledge_assets/builders/semantic/mdl_writer.py`
- `frontend/server/knowledge_assets/builders/semantic/schema_graph.py`
- `frontend/server/knowledge_assets/builders/semantic/metric_dimension_candidates.py`
- `frontend/server/knowledge_assets/builders/semantic/skill_package_writer.py`
- `frontend/server/knowledge_assets/routes.py`
- `frontend/server/knowledge_assets/models.py`
- `frontend/server/knowledge_assets/repository.py`
- `frontend/src/adk/knowledgeAssets.ts`

Key boundary found:

- Frontend start path streams semantic build events and then reads the build job / pack detail.
- Backend semantic builder previously had deterministic builder steps and staged SSE events, but J3 needs an explicit audited `InternalAgentRunner.run` boundary.
- The repository already stores semantic packs, events, jobs, and question-SQL / instructions; J3 extends it with conversation, draft revision, agent run metadata, document source IDs, and explicit publish actions.

## Wren mapping

Wren CLI guidance reviewed:

- `wren skills get generate-mdl --full`
- `wren skills get enrich-context --full`
- `wren skills get usage --full`

Relevant concepts mapped into J3:

- Schema scope and database dialect remain explicit in runner context.
- MDL is treated as the source of truth for models, relationships, metrics, dimensions, and views.
- Question-SQL pairs and user instructions are retained as context and written into the capability package.
- Context enrichment follows “add/augment without overwriting unreviewed business meaning”.
- SQL execution is not claimed during draft View generation; generated SQL/query specs are draft artifacts unless validated by an available execution path.

Out of scope:

- No Wren Apollo, Next Router, iframe, remote Wren UI, or runtime service was introduced.

## Semantica mapping

Semantica references reviewed:

- `/Users/bytedance/semantica/docs/guides/semantic-extraction.md`
- `/Users/bytedance/semantica/docs/guides/ontology.md`
- `/Users/bytedance/semantica/docs/guides/provenance.md`
- `/Users/bytedance/semantica/docs/guides/pipeline.md`
- `/Users/bytedance/semantica/semantica/semantic_extract/`

Concepts reused:

- Document contexts become evidence fragments, doc graph, ontology candidates, and provenance.
- Schema/document alignment is recorded as alignment records instead of implicit prompt-only state.
- Confidence and suggested status are preserved for inferred relationships and generated views.
- Document-only flow can create doc/retrieval context without fabricating SQL metrics or database models.

Out of scope:

- No external Semantica service dependency was added.
- Fallback and deterministic preprocessing are marked honestly and are not reported as Agent completion.

## Resulting design decision

J3 inserts a narrow audited runner boundary:

1. Deterministic code prepares schema graph, candidate MDL seed, document graph, few-shot, instructions, and provenance.
2. `SemanticBuilderAgent` calls `InternalAgentRunner.run` for `operation=start`.
3. Refine calls `InternalAgentRunner.run` for `operation=refine` with current draft MDL and current revision.
4. Runner output is schema-validated; conservative JSON envelope repair is recorded in `validation_result` when used.
5. Draft package and revision history are persisted first; Publish is only allowed through the explicit publish endpoint and gate.

