# OpenViking integration acceptance

Status: `OPENVIKING_INTEGRATION_ACCEPTANCE_BLOCKED`

Baseline: `5948d5dd3b29358591b81da2390dc69ff922760c`  
Final: `5948d5dd3b29358591b81da2390dc69ff922760c`  
Remote baseline: `5948d5dd3b29358591b81da2390dc69ff922760c`  
Validation worktree: clean; no source fix was needed or authorized without a real repro.

The BFF and UI contract surfaces are present. Server contract tests passed
(136 passed), OpenViking deletion isolation passed, Python compilation passed,
and the static UI/isolation suite passed (7 passed, 2 explicitly skipped).
The live BFF smoke reached the running Studio but returned
`OPENVIKING_UNAVAILABLE`; no real import task was created.

Import matrix: all eight minimum types and the additional UI-declared
DOCX/PPTX/HTML/image/directory/batch/Git/Feishu paths are
`BLOCKED_EXTERNAL`, because task success, content read, canary search,
refresh/restart recovery, and deletion could not be proven against a live
upstream.

KnowledgeSourceRef: contract-level PASS. The shape is provider/profile plus
signed opaque resource ref, with server-side tenant/workspace/profile
authorization. Live Skill Creator delivery is `BLOCKED_EXTERNAL`.

Security: contract checks for encryption/masking, SSRF policy, signed-ref
tamper rejection, cross-scope rejection, and revoke fail-closed passed.
Live wrong-key and revoke-after-real-import checks remain blocked.

Remaining blockers:

- Required `OPENVIKING_E2E_BASE_URL` and `OPENVIKING_E2E_API_KEY` were not
  available in this run.
- The frontend dependency tree is absent in the fresh worktree, so
  `cd frontend && npm run typecheck` fails during module/type resolution;
  this is an environment setup blocker, not a diagnosed source error.
- No commit/push was made because acceptance is not frozen.

Evidence files are in
`docs/knowledge-workspace/evidence/openviking-integration-acceptance/`.
