# ADR: TemplateSpec builds Skills; SkillViewRevision renders executions

Status: accepted for STEP3B Worker 3
Date: 2026-08-25

## Decision

There is one publishable artifact: `Skill`.

- `SkillKind` describes the callable capability and its typed execution contract.
- `TemplateSpec(templateId, version, digest)` describes a reusable construction
  method: scenario, required immutable context kinds, input schema, capability
  intent, instructions, evidence rules, quality gates, renderer, tools/actions,
  and compatibility.
- `SkillDraftRevision` pins a `TemplateRef`, context revision references, typed
  `KindSpec`, and input/output schemas. A BuildPlan remains internal.
- `SkillViewRevision` is immutable output for one Skill revision. Trusted
  server renderers convert typed ViewModels to inert HTML with CSP, digest,
  ETag, trace, and data revision lineage.

Dashboard, Semantic, SOP, Knowledge, Graph/Ontology, and Monitoring are
TemplateSpec/default renderer pairs. They are not independently publishable
artifact kinds.

## SOP

`sop` is an explicit `SkillKind`, never inferred from a title or filename.
`SopKindSpec` defines trigger/scope, typed inputs, ordered/branch steps,
conditions, versioned tools, evidence requirements, outputs, failure handling,
and action proposal. Trial runs execute read-only tools from supplied tool
results. External writes and high-risk operations only produce a confirmation
challenge.

## Compatibility and migration

Existing `data_access`, `knowledge`, `semantic`, `analysis`,
`graph_ontology`, and `monitoring` manifests remain valid because
`templateRef` and `contextRevisionRefs` are optional at the legacy boundary.
The new Template Skill Builder requires both and validates capability intent.
This moves new authoring to the unified model without rewriting old revisions.

TemplateSpec rows are persisted by migration `007_template_specs`; built-ins
use the reserved `__builtin__` workspace and cannot be mutated. Copying creates
a workspace-owned, separately versioned spec.md. Reusing a version with
different content is rejected.

## Security

Renderers do not accept HTML or scripts from models. Output has no iframe,
network URL, or executable script and declares a restrictive CSP. Runtime
rejects Skill and Golden Asset ownership mismatches. Semantic dependencies
must pin an immutable revision and matching schema digest.
