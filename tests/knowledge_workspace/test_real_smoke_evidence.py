from __future__ import annotations

import json

from tools.connection_autoskill_real_smoke import persist_progress


def test_real_smoke_persists_redacted_progress_and_private_resume_state(
    tmp_path,
) -> None:
    evidence = tmp_path / "evidence.json"
    resume = tmp_path / "resume.json"
    result = {
        "status": "RUNNING",
        "agent_id": "abcd…wxyz",
        "connection_id": "1234…7890",
        "requests": [{"kind": "create_skill"}],
    }
    private = {
        "agent_id": "agent-secret-id",
        "connection_id": "connection-secret-id",
        "skill_name": "safe-skill-name",
    }

    persist_progress(evidence, result, resume_path=resume, resume=private)

    assert json.loads(evidence.read_text()) == result
    assert "agent-secret-id" not in evidence.read_text()
    assert json.loads(resume.read_text()) == private
    assert resume.stat().st_mode & 0o777 == 0o600
