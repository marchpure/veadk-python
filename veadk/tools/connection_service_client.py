"""Small server-side client for the independent Connection Service.

This module is intentionally not imported by Studio browser code. It carries
the STEP 2B contract for BFF/worker integrations and never accepts credentials
in a browser-facing DTO.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import httpx


@dataclass(frozen=True)
class ConnectionServiceClient:
    base_url: str
    bearer_token: str
    timeout_seconds: float = 30.0

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.bearer_token}"
        response = httpx.request(
            method,
            f"{self.base_url.rstrip('/')}{path}",
            headers=headers,
            timeout=self.timeout_seconds,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def list_enabled_connectors(self) -> Mapping[str, Any]:
        return self._request("GET", "/v1/catalog").json()

    def list_connections(self) -> Mapping[str, Any]:
        return self._request("GET", "/v1/connections").json()

    def issue_lease(
        self,
        connection_id: str,
        *,
        invocation_id: str,
        audience: str,
        allowed_actions: list[str],
        ttl_seconds: int = 300,
    ) -> Mapping[str, Any]:
        if not connection_id or not allowed_actions:
            raise ValueError("connection_id and allowed_actions must be non-empty")
        return self._request(
            "POST",
            f"/v1/connections/{connection_id}/lease",
            json={
                "invocationId": invocation_id,
                "audience": audience,
                "allowedActions": allowed_actions,
                "ttlSeconds": ttl_seconds,
            },
        ).json()

    def execute(
        self,
        action_id: str,
        *,
        connection_id: str,
        invocation_id: str,
        audience: str,
        lease_token: str,
        input: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._request(
            "POST",
            f"/v1/runtime/actions/{action_id}",
            headers={"X-Connection-Lease": lease_token},
            json={
                "connectionId": connection_id,
                "invocationId": invocation_id,
                "audience": audience,
                "input": dict(input),
            },
        ).json()
