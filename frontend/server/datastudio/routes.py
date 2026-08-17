# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""FastAPI transport for the Studio Data Studio gateway."""

from __future__ import annotations

from fastapi import FastAPI, Request

from .models import DataStudioAssetType
from .service import (
    config_payload,
    configured_origin,
    proxy_external_asset,
    proxy_external_assets,
    require_configured,
)


def mount_datastudio_routes(app: FastAPI) -> None:
    @app.get("/web/datastudio/config")
    async def _web_datastudio_config():
        config = config_payload()
        if not config.configured:
            require_configured()
        payload = config.model_dump(mode="json")
        payload["origin"] = configured_origin(config)
        return payload

    @app.get("/web/datastudio/assets")
    async def _web_datastudio_assets(request: Request):
        return await proxy_external_assets(request)

    @app.get("/web/datastudio/assets/{asset_type}/{asset_id}")
    async def _web_datastudio_asset(asset_type: DataStudioAssetType, asset_id: str):
        return await proxy_external_asset(asset_type, asset_id)
