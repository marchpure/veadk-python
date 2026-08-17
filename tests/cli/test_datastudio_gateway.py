from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException
from starlette.datastructures import QueryParams

from frontend.server.datastudio import gateways as datastudio_gateways
from frontend.server.datastudio import service as datastudio_service
from frontend.server.datastudio.routes import mount_datastudio_routes


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
    response = _FakeResponse(200, {"data": {"items": [], "total": 0}})

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
        "DATASTUDIO_MOCK",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_datastudio_routes_mount_on_fastapi_app() -> None:
    app = FastAPI()
    mount_datastudio_routes(app)
    paths = {getattr(route, "path", "") for route in app.router.routes}

    assert "/web/datastudio/config" in paths
    assert "/web/datastudio/assets" in paths
    assert "/web/datastudio/assets/{asset_type}/{asset_id}" in paths


@pytest.mark.asyncio
async def test_datastudio_asset_proxy_maps_byaan_response_and_keeps_query_url_relative(
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
                        "publish_state": "published",
                        "gate": {"score": 99},
                        "query_url": "/api/external/assets/dashboard/sales/query",
                    }
                ],
                "total": 1,
            },
        },
    )
    monkeypatch.setattr(datastudio_gateways.httpx, "AsyncClient", _FakeAsyncClient)

    payload = await datastudio_service.proxy_external_assets(_RequestStub("q=sales"))

    assert _FakeAsyncClient.calls == [
        {
            "url": "https://byaan.example/api/external/assets",
            "params": {"types": "dashboard,semantic_model", "q": "sales", "limit": "20"},
            "headers": {"Authorization": "Bearer server-only-secret"},
        }
    ]
    assert payload["assets"][0]["query_url"] == "/api/external/assets/dashboard/sales/query"
    assert "server-only-secret" not in json.dumps(payload)


def test_datastudio_proxy_rejects_cross_origin_query_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")

    with pytest.raises(HTTPException) as exc_info:
        datastudio_service.normalize_asset(
            {
                "asset_type": "dashboard",
                "asset_id": "sales",
                "name": "Sales",
                "publish_state": "published",
                "query_url": "https://evil.example/api/external/assets/dashboard/sales/query",
            }
        )
    assert exc_info.value.status_code == 502
