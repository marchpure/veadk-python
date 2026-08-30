# Skill Workshop v2.20.12.1

The Knowledge Workspace Skill flow is conversation-led:

1. Describe a business task.
2. Select at least one real Connection or Resource from the BFF-backed drawer.
3. Send the first message to create a Draft and start its first generation Invocation.
4. Continue in the three-pane workshop: real Invocation history, conversation, and Artifact preview.
5. Run the current Revision explicitly, publish it, then add the published Skill to an Agent.

The canonical entry is `?view=knowledge-workspace`. The former
`file=skill_new` deep link renders the same creator and state model, while
`file=welcome` is replaced in-place with the canonical URL before paint. Brand
and “工作台” navigation return to the canonical creator; explicit “创建” and
“新建 Skill” actions reset any unsubmitted task, template, context selections,
and errors. Inspecting a Connection or Resource from the context drawer keeps
that in-progress creator state when returning.

The create composer defaults to `generic` with `{ "mode": "auto" }`. Semantic,
Dashboard, and SOP remain optional single-choice hints using their existing
template configurations.

Connection removal affects only the current Skill. Existing Draft changes are
persisted with `PATCH /api/knowledge/v1/skills/drafts/{draft_id}`. The frontend
does not create, validate, discover, or simulate Connection Service records.

## Backend limits

- The service does not expose multi-AuthoringSession CRUD. The left rail
  therefore shows real Invocations grouped by date and does not offer a fake
  “new session”.
- Agent directory/binding APIs are not exposed by the current Knowledge
  Workspace service. The bind surface reads the existing real Runtime directory,
  but keeps binding disabled and explains the missing API rather than claiming
  success.
- The current BFF has no access-controlled result-snapshot sharing endpoint.
  The share surface identifies the real Invocation but stays explicitly
  disabled instead of generating a local or unauthorised link.
- Publication refresh uses the existing BFF publication listing and matches
  published records to the Draft's real Revision IDs.

## Verification evidence

Screenshots and measured layout bounds are under
`docs/knowledge-workspace/evidence/skill-workshop-v220121/`.

Default-entry evidence is:

- `08-default-root-1440x1000.png`
- `09-compatible-skill-new-1440x1000.png`
- `10-default-root-1280x800.png`
- `11-default-root-390x844.png`

The capture harness uses Playwright route fixtures only for deterministic
frontend contract and visual verification. It asserts one Draft creation, one
generation request, real-shaped SSE replay, Artifact restoration, publication
gating, no console/page errors, no static 404s, and responsive bounds. It is
not evidence of a live AutoSkill generation.

Real dependency probe on 2026-08-30:

- Connection Service `http://127.0.0.1:38200/health`: HTTP 200.
- Its direct connector catalog correctly required a bearer token (HTTP 401).
- A running Studio BFF at `http://127.0.0.1:37863` returned connector
  definitions and one `ready` PostgreSQL Connection.
- That BFF rejected the required W4 `template_key` and `template_config`
  fields with HTTP 422. No Draft was created. Real generation is therefore
  `BLOCKED_EXTERNAL` until a Studio BFF from the specified W4 baseline is
  running with the frozen Connection Service and AutoSkill configuration.
