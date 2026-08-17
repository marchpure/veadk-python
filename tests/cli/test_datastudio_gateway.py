from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from starlette.datastructures import QueryParams

from veadk.cli import datastudio_gateway


class _RequestStub:
    def __init__(self, query: str = "") -> None:
        self.query_params = QueryParams(query)


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> object:
        return self._payload


class _FakeAsyncClient:
    calls: list[dict[str, object]] = []
    response = _FakeResponse(200, {"assets": []})

    def __init__(self, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.response


@pytest.fixture(autouse=True)
def clear_datastudio_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "DATASTUDIO_API_KEY",
        "DATASTUDIO_BASE_URL",
        "DATASTUDIO_EMBED_URL",
        "DATASTUDIO_MCP_URL",
        "DATASTUDIO_MOCK",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_datastudio_config_hides_key_and_requires_server_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATASTUDIO_API_KEY", "server-only-secret")

    config = datastudio_gateway.config_payload()

    assert config.configured is False
    assert "server-only-secret" not in json.dumps(config.model_dump(mode="json"))
    with pytest.raises(HTTPException) as exc_info:
        datastudio_gateway.require_configured()
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_datastudio_mock_assets_work_without_iframe_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATASTUDIO_MOCK", "true")

    config = datastudio_gateway.config_payload()
    payload = await datastudio_gateway.proxy_external_assets(_RequestStub("q=留存"))

    assert config.configured is False
    assert config.embedUrl == ""
    assert payload["mock"] is True
    assert payload["assets"][0]["asset_type"] == "semantic_model"


@pytest.mark.asyncio
async def test_datastudio_asset_proxy_sends_credentials_server_side_and_normalizes_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")
    monkeypatch.setenv("DATASTUDIO_API_KEY", "server-only-secret")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(
        200,
        {
            "items": [
                {
                    "asset_type": "dashboard",
                    "asset_id": "sales",
                    "name": "Sales",
                    "description": "Revenue",
                    "status": "published",
                    "publish_state": "published",
                    "gate": {"score": 99},
                    "version": "v1",
                    "consumers": ["agent"],
                    "capabilities": {},
                    "freshness": {},
                    "provenance": {},
                    "usage_policy": {},
                    "sample_evidence": [],
                },
                {
                    "asset_type": "dashboard",
                    "asset_id": "draft",
                    "name": "Draft",
                    "publish_state": "draft",
                },
            ],
            "total": 2,
            "page": 1,
            "page_size": 20,
        },
    )
    monkeypatch.setattr(datastudio_gateway.httpx, "AsyncClient", _FakeAsyncClient)

    payload = await datastudio_gateway.proxy_external_assets(_RequestStub("q=sales"))

    assert _FakeAsyncClient.calls == [
        {
            "url": "https://byaan.example/api/external/assets",
            "params": {"q": "sales"},
            "headers": {
                "Authorization": "Bearer server-only-secret",
                "X-API-Key": "server-only-secret",
            },
        }
    ]
    assert len(payload["assets"]) == 1
    assert payload["assets"][0]["mcp_url"] == (
        "https://byaan.example/api/mcp/assets/dashboard/sales"
    )
    assert "server-only-secret" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_datastudio_asset_proxy_maps_byaan_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")
    monkeypatch.setenv("DATASTUDIO_API_KEY", "server-only-secret")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(401, {"detail": "unauthorized"})
    monkeypatch.setattr(datastudio_gateway.httpx, "AsyncClient", _FakeAsyncClient)

    with pytest.raises(HTTPException) as exc_info:
        await datastudio_gateway.proxy_external_assets(_RequestStub())

    assert exc_info.value.status_code == 401
