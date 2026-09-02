"""Agent Identity credential custody for one-time Runtime Token material."""

from __future__ import annotations

import asyncio
import re
from typing import Callable, Protocol

from veadk.integrations.ve_identity.identity_client import IdentityClient

from .client import AgentKitMcpError


class CredentialProviderPort(Protocol):
    async def create(self, *, name: str, plaintext: str) -> str: ...

    async def delete(self, provider_ref: str) -> None: ...


class IdentityApiKeyCredentialProvider:
    def __init__(
        self,
        *,
        credential_resolver: Callable[[], tuple[str, str, str | None]],
        region: str,
        pool_name: str | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver
        self._region = region
        self._pool_name = pool_name

    def _client(self) -> IdentityClient:
        access_key, secret_key, session_token = self._credential_resolver()
        return IdentityClient(
            access_key=access_key,
            secret_key=secret_key,
            session_token=session_token or "",
            region=self._region,
        )

    async def create(self, *, name: str, plaintext: str) -> str:
        provider_name = _provider_name(name)
        try:
            response = await asyncio.to_thread(
                self._client().create_api_key_credential_provider,
                {
                    "name": provider_name,
                    "pool_name": self._pool_name,
                    "project_name": "default",
                    "api_key": plaintext,
                    "api_key_metadata": [
                        {
                            "location": "HEADER",
                            "parameter_name": "Authorization",
                            "prefix": "Bearer ",
                        }
                    ],
                    "source": "Custom",
                },
            )
        except Exception as error:
            raise AgentKitMcpError(
                "UPSTREAM_CREDENTIAL_FAILED",
                "Agent Identity could not custody the publication credential",
                retryable=True,
            ) from error
        returned_name = str(getattr(response, "name", "") or provider_name)
        return f"credential-provider://{returned_name}"

    async def delete(self, provider_ref: str) -> None:
        provider_name = provider_ref.removeprefix("credential-provider://")
        if not provider_name:
            return
        try:
            import volcenginesdkid

            client = self._client()
            await asyncio.to_thread(
                client._api_client.delete_api_key_credential_provider,
                volcenginesdkid.DeleteApiKeyCredentialProviderRequest(
                    name=provider_name, pool_name=self._pool_name
                ),
            )
        except Exception as error:
            raise AgentKitMcpError(
                "UPSTREAM_CREDENTIAL_FAILED",
                "Agent Identity could not remove the publication credential",
                retryable=True,
            ) from error


def _provider_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")
    return (normalized or "dw-mcp-provider")[:64]
