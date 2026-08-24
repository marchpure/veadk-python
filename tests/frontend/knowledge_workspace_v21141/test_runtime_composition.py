from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets.runtime import create_app


def test_runtime_composition_requires_authenticated_identity_resolver() -> None:
    with pytest.raises(ValueError, match="identity_resolver"):
        create_app(repository_path=":memory:")


def test_runtime_composition_reaches_real_bff(tmp_path: Path) -> None:
    app = create_app(
        repository_path=tmp_path / "assets.sqlite3",
        identity_resolver=lambda request: ("workspace-runtime", "editor"),
    )
    response = TestClient(app).get(
        "/api/knowledge-assets/v1/bootstrap",
        headers={"X-Request-ID": "runtime-bootstrap"},
    )
    assert response.status_code == 200
    assert response.json()["access"]["spaceId"] == "workspace-runtime"
