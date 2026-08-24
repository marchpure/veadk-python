# STEP3 Worker 2 UI proposal

Status: proposal for Main. No frozen UI or shared shell files were changed.

The existing Composer and single right-side assistant should consume the
`AuthoringReadModel` and use the following bindings:

| UI action | typed operation | required read-model evidence |
| --- | --- | --- |
| Send Composer | `skill_draft.create` | operation status, BuildPlan digest, draft revision, trace |
| Add/remove/drag resource | `skill_draft.context.update` | deduplicated refs, fixed revisions, context digest |
| Choose kind | `skill_draft.create` | one of the five typed `kind_spec` variants |
| Accept assistant change | `skill_draft.patch.accept` | impact summary, base revision, new revision |
| Reject assistant change | `skill_draft.patch.reject` | audit event, unchanged draft revision |
| Undo | `skill_draft.undo` | new revision with `undo_of_revision` |
| Comment repair | `skill_draft.patch.propose` then accept | patch and affected paths |
| Refresh/reopen | `skill_draft.read` | current operation, draft revision, event sequence |
| Run/debug | `skill_draft.execute` | Worker 3 acceptance, not a fabricated result |
| Reuse team | `skill_draft.team.reuse` | personal scope, source lineage, draft state |

Right-pane context should be derived from `current_skill_id`,
`current_view_id`, `current_component_id`, and comment IDs in the envelope.
Opening a different resource must construct a new envelope and re-authorize
references; the assistant must not retain a browser store snapshot.

Presentation-only patches (`set_title`, `set_description`) can update the draft
without rerun. Query, metric, permission, freshness, semantic mapping,
citation, and alert patches must show `requires_rerun=true` and keep the draft
in `ready_for_execution` until Worker 3 accepts the typed request.

Team read-only objects must not expose an accept button. “Reuse as personal
draft” calls `skill_draft.team.reuse`; personal scope and source lineage should
be visible. Evaluation remains Worker 4-owned.
