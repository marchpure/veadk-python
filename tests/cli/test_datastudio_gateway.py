from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from starlette.datastructures import QueryParams

from veadk.cli.cli_web import patch_adk_fast_api_datastudio_routes
from frontend.server.datastudio import gateways as datastudio_gateways
from frontend.server.datastudio import service as datastudio_gateway


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
    response = _FakeResponse(200, {"data": {"items": [], "total": 0, "next_cursor": None}})

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


def test_datastudio_routes_mount_on_real_veadk_web_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    import google.adk.cli.fast_api as adk_fast_api

    original = adk_fast_api.get_fast_api_app

    def fake_get_fast_api_app(*_args: object, **_kwargs: object) -> FastAPI:
        return FastAPI()

    monkeypatch.setattr(adk_fast_api, "get_fast_api_app", fake_get_fast_api_app)
    patch_adk_fast_api_datastudio_routes()

    app = adk_fast_api.get_fast_api_app(agents_dir=".", web=True)
    paths = {getattr(route, "path", "") for route in app.router.routes}

    assert "/web/datastudio/config" in paths
    assert "/web/datastudio/assets" in paths
    assert "/web/datastudio/assets/{asset_type}/{asset_id}" in paths

    monkeypatch.setattr(adk_fast_api, "get_fast_api_app", original)


@pytest.mark.asyncio
async def test_datastudio_asset_proxy_maps_byaan_standard_response_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")
    monkeypatch.setenv("DATASTUDIO_API_KEY", "server-only-secret")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(
        200,
        {
            "success": True,
            "data": {
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
                        "capabilities": {"metrics": ["GMV"]},
                        "query_url": "/api/external/assets/dashboard/sales/query",
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
                "next_cursor": "20",
            },
        },
    )
    monkeypatch.setattr(datastudio_gateways.httpx, "AsyncClient", _FakeAsyncClient)

    payload = await datastudio_gateway.proxy_external_assets(_RequestStub("q=sales&page=2&page_size=10"))

    assert _FakeAsyncClient.calls == [
        {
            "url": "https://byaan.example/api/external/assets",
            "params": {"types": "dashboard,semantic_model", "q": "sales", "limit": "10", "cursor": "10"},
            "headers": {"Authorization": "Bearer server-only-secret"},
        }
    ]
    assert payload["total"] == 2
    assert payload["nextCursor"] == "20"
    assert len(payload["assets"]) == 1
    assert payload["assets"][0]["query_url"] == "https://byaan.example/api/external/assets/dashboard/sales/query"
    assert "mcp_url" not in payload["assets"][0]
    assert "server-only-secret" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_datastudio_asset_proxy_maps_byaan_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")
    monkeypatch.setenv("DATASTUDIO_API_KEY", "server-only-secret")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(401, {"detail": "unauthorized"})
    monkeypatch.setattr(datastudio_gateways.httpx, "AsyncClient", _FakeAsyncClient)

    with pytest.raises(HTTPException) as exc_info:
        await datastudio_gateway.proxy_external_assets(_RequestStub())

    assert exc_info.value.status_code == 401
