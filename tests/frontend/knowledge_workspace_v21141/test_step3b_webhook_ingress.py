from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient

from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
)
from frontend.server.knowledge_assets.sources_golden.webhook_ingress import (
    create_webhook_ingress,
)


def _context() -> AccessContext:
    return AccessContext(
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        role="editor",
    )


def _client(tmp_path: Path, *, rate_limit: int = 2) -> tuple[TestClient, str, str]:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "event.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["sku", "stock"],
                "properties": {
                    "sku": {"type": "string"},
                    "stock": {"type": "integer"},
                },
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    secret = "webhook-ingress-secret"
    application = SourceGoldenApplication(
        database_path=tmp_path / "webhook.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=uploads,
        secret_resolver=lambda _ref: secret,
    )
    connection = application.create_connection(
        _context(),
        connector_key="webhook",
        display_name="Webhook ingress",
        scope="team",
        configuration={
            "listenPath": "/inventory/events",
            "schemaRef": "event.schema.json",
            "rateLimitPerMinute": rate_limit,
        },
        secret_ref="secret://workspace-step3b/webhook",
        idempotency_key="webhook-ingress-create",
        trace_id="trace-webhook-ingress-create",
    ).connection
    app = create_webhook_ingress(
        application,
        context_resolver=lambda workspace_id, _connection_id: AccessContext(
            workspace_id=workspace_id,
            principal_id="webhook-ingress",
            role="editor",
        ),
    )
    return TestClient(app), connection.id, secret


def _headers(secret: str, delivery_id: str, body: bytes) -> dict[str, str]:
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Webhook-Id": delivery_id,
        "X-Webhook-Signature": f"sha256={signature}",
        "X-Trace-Id": f"trace-{delivery_id}",
    }


def _url(connection_id: str) -> str:
    return f"/workspaces/workspace-step3b/connections/{connection_id}/inventory/events"


def test_webhook_ingress_accepts_signed_schema_valid_delivery(
    tmp_path: Path,
) -> None:
    client, connection_id, secret = _client(tmp_path)
    body = b'{"sku":"A-1","stock":8}'

    response = client.post(
        _url(connection_id),
        content=body,
        headers=_headers(secret, "delivery-1", body),
    )

    assert response.status_code == 202
    assert response.json()["eventType"] == "webhook.delivery.accepted"
    assert response.json()["traceId"] == "trace-delivery-1"


def test_webhook_ingress_maps_auth_schema_and_replay_errors(
    tmp_path: Path,
) -> None:
    client, connection_id, secret = _client(tmp_path)
    valid = b'{"sku":"A-1","stock":8}'

    bad_signature = client.post(
        _url(connection_id),
        content=valid,
        headers={
            **_headers(secret, "bad-signature", valid),
            "X-Webhook-Signature": "sha256=wrong",
        },
    )
    invalid = b'{"sku":"A-1","stock":"many"}'
    bad_schema = client.post(
        _url(connection_id),
        content=invalid,
        headers=_headers(secret, "bad-schema", invalid),
    )
    accepted = client.post(
        _url(connection_id),
        content=valid,
        headers=_headers(secret, "delivery-1", valid),
    )
    replay = client.post(
        _url(connection_id),
        content=valid,
        headers=_headers(secret, "delivery-1", valid),
    )

    assert bad_signature.status_code == 401
    assert bad_signature.json()["code"] == "WEBHOOK_AUTHENTICATION_FAILED"
    assert bad_schema.status_code == 422
    assert bad_schema.json()["code"] == "WEBHOOK_SCHEMA_INVALID"
    assert accepted.status_code == 202
    assert replay.status_code == 409
    assert replay.json()["code"] == "WEBHOOK_REPLAY"


def test_webhook_ingress_maps_rate_limit_and_protocol_errors(
    tmp_path: Path,
) -> None:
    client, connection_id, secret = _client(tmp_path, rate_limit=1)
    valid = b'{"sku":"A-1","stock":8}'
    wrong_path = client.post(
        _url(connection_id).replace("/inventory/events", "/wrong"),
        content=valid,
        headers=_headers(secret, "wrong-path", valid),
    )
    wrong_type = client.post(
        _url(connection_id),
        content=valid,
        headers={
            **_headers(secret, "wrong-type", valid),
            "Content-Type": "text/plain",
        },
    )
    accepted = client.post(
        _url(connection_id),
        content=valid,
        headers=_headers(secret, "delivery-1", valid),
    )
    limited = client.post(
        _url(connection_id),
        content=valid,
        headers=_headers(secret, "delivery-2", valid),
    )

    assert wrong_path.status_code == 404
    assert wrong_path.json()["code"] == "WEBHOOK_PATH_MISMATCH"
    assert wrong_type.status_code == 415
    assert wrong_type.json()["code"] == "WEBHOOK_CONTENT_TYPE_INVALID"
    assert accepted.status_code == 202
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.json()["code"] == "WEBHOOK_RATE_LIMIT"


def test_webhook_ingress_rejects_payload_over_connection_limit(
    tmp_path: Path,
) -> None:
    client, connection_id, secret = _client(tmp_path)
    body = b'{"sku":"' + (b"A" * 1_000_000) + b'","stock":8}'

    response = client.post(
        _url(connection_id),
        content=body,
        headers=_headers(secret, "oversized-delivery", body),
    )

    assert response.status_code == 413
    assert response.json()["code"] == "WEBHOOK_PAYLOAD_LIMIT"
