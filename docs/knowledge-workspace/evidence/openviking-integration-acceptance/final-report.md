# OpenViking integration acceptance

Status: `OPENVIKING_INTEGRATION_ACCEPTANCE_FROZEN`

The packaged production UI was rebuilt from the current TypeScript source and served directly by the isolated BFF at `http://127.0.0.1:38112`. The build preserves `lazy(loadOpenVikingWorkspace)` and emits OpenViking as an independent production chunk. The production HTML renderer no longer appends the local `view` route parameter to entry-module URLs, preventing the entry and lazy chunk from resolving different React module identities. Gateway query parameters remain forwarded without re-encoding.

The OpenViking isolation test, focused frontend tests, typecheck, production build, and built-assets verifier passed. The verifier checked 103 packaged WebUI files and 296 internal references. The complete `veadk/webui` release tree contains no Git conflict markers, and `git diff --check` passed.

Desktop (1440×900) and narrow-screen (390×844) Playwright journeys used both required direct URLs, with no OpenViking request interception. Both passed Ready-first/stale profile recovery, profile creation and validation, masked credentials, manual import, task history, refresh recovery, resource tree and preview, retrieval, deletion, Skill Creator selection, and revocation. No profile-not-found 404 or profile-not-ready 409 was observed.

Per the final short-close instruction, the previously passed browser journeys, live API/import matrix, restart recovery, and KnowledgeSourceRef boundary were carried forward and not rerun. The live import matrix remains PASS for manual text, URL/web, TXT, Markdown, PDF, CSV, JSON, and XLSX. Unsupported formats and integrations are recorded as `NOT_SUPPORTED` in the capability inventory.

All evidence is redacted. No API key, encryption key, signing key, or plaintext third-party credential is stored here.
