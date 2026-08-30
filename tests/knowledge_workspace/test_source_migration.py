from __future__ import annotations

import json

from frontend.server.knowledge_workspace.models import SkillDraft
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository


def test_legacy_draft_payload_hydrates_and_next_save_is_canonical() -> None:
    repository = KnowledgeWorkspaceRepository()
    draft = {
        "tenant_id": "tenant",
        "workspace_id": "workspace",
        "draft_id": "draft-legacy",
        "created_by": "principal",
        "goal": "legacy",
        "connection_ids": [],
        "resource_ids": [],
        "openviking_profile_ids": ["p1", "p1"],
        "openviking_resource_refs": ["r1"],
        "upload_ids": [],
        "status": "editing",
        "current_revision_id": None,
        "etag": "etag-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    repository._db.execute(
        "INSERT INTO kw_drafts(id,tenant_id,workspace_id,payload) VALUES(?,?,?,?)",
        ("draft-legacy", "tenant", "workspace", json.dumps(draft)),
    )
    loaded = repository.get_draft("draft-legacy", tenant_id="tenant", workspace_id="workspace")
    assert loaded is not None
    assert [ref.profile_ref for ref in loaded.knowledge_source_refs if ref.profile_ref] == ["p1"]
    assert [ref.resource_ref for ref in loaded.knowledge_source_refs if ref.resource_ref] == ["r1"]
    repository.save_draft(loaded)
    payload = repository._db.execute("SELECT payload FROM kw_drafts WHERE id=?", ("draft-legacy",)).fetchone()[0]
    assert "knowledge_source_refs" in payload
    assert "openviking_profile_ids" not in payload
    assert "openviking_resource_refs" not in payload
