"""Live Gateway verification through Agent Identity OAuth M2M."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)

from veadk.integrations.ve_identity import VeIdentityMcpToolset, oauth2_auth
from veadk.integrations.ve_identity.identity_client import IdentityClient
from veadk.integrations.ve_identity.utils import generate_headers

from .client import AgentKitMcpError
from .models import AgentKitMcpPublication, GatewayVerification

CredentialResolver = Callable[[], tuple[str, str, str | None]]


class _VerificationContext:
    def __init__(self, workload_identity: str) -> None:
        self._invocation_context = SimpleNamespace(
            user_id="",
            session=SimpleNamespace(state={}),
        )
        self.agent_name = workload_identity

    @property
    def state(self) -> dict[str, Any]:
        return self._invocation_context.session.state


class _BoundIdentityClient(IdentityClient):
    def __init__(self, *, workload_identity: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workload_identity = workload_identity

    def get_workload_access_token(
        self,
        workload_name: str | None = None,
        user_token: str | None = None,
        user_id: str | None = None,
    ):
        return super().get_workload_access_token(
            workload_name=workload_name or self._workload_identity,
            user_token=user_token,
            user_id=user_id or None,
        )


class IdentityM2MGatewayVerifier:
    """Prove initialize, tools/list, allowed call, and server-side denial."""

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver,
        region: str,
        workload_identity: str,
        oauth_provider: str,
        allowed_tool: str,
        allowed_arguments: dict[str, Any],
        denied_tool: str,
        denied_arguments: dict[str, Any],
        denied_error_marker: str,
        scopes: list[str] | None = None,
        timeout_seconds: float = 60,
    ) -> None:
        self._credential_resolver = credential_resolver
        self._region = region
        self._workload_identity = workload_identity
        self._oauth_provider = oauth_provider
        self._allowed_tool = allowed_tool
        self._allowed_arguments = allowed_arguments
        self._denied_tool = denied_tool
        self._denied_arguments = denied_arguments
        self._denied_error_marker = denied_error_marker
        self._scopes = scopes or ["openid"]
        self._timeout = timeout_seconds

    @classmethod
    def from_env(
        cls,
        *,
        credential_resolver: CredentialResolver,
        region: str,
    ) -> "IdentityM2MGatewayVerifier | None":
        workload = os.getenv(
            "DATA_WORKSHOP_MCP_VERIFY_WORKLOAD_IDENTITY", ""
        ).strip()
        provider = os.getenv("DATA_WORKSHOP_MCP_VERIFY_OAUTH_PROVIDER", "").strip()
        allowed_tool = os.getenv(
            "DATA_WORKSHOP_MCP_VERIFY_ALLOWED_TOOL", ""
        ).strip()
        denied_tool = os.getenv("DATA_WORKSHOP_MCP_VERIFY_DENIED_TOOL", "").strip()
        denied_error_marker = os.getenv(
            "DATA_WORKSHOP_MCP_VERIFY_DENIED_ERROR_MARKER", ""
        ).strip()
        if not all(
            (workload, provider, allowed_tool, denied_tool, denied_error_marker)
        ):
            return None
        try:
            allowed_arguments = _json_object_env(
                "DATA_WORKSHOP_MCP_VERIFY_ALLOWED_ARGUMENTS"
            )
            denied_arguments = _json_object_env(
                "DATA_WORKSHOP_MCP_VERIFY_DENIED_ARGUMENTS"
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Data Workshop MCP verification arguments must be JSON objects"
            ) from error
        scopes = [
            value.strip()
            for value in os.getenv(
                "DATA_WORKSHOP_MCP_VERIFY_OAUTH_SCOPES", "openid"
            ).split(",")
            if value.strip()
        ]
        return cls(
            credential_resolver=credential_resolver,
            region=region,
            workload_identity=workload,
            oauth_provider=provider,
            allowed_tool=allowed_tool,
            allowed_arguments=allowed_arguments,
            denied_tool=denied_tool,
            denied_arguments=denied_arguments,
            denied_error_marker=denied_error_marker,
            scopes=scopes,
        )

    async def verify(
        self, publication: AgentKitMcpPublication
    ) -> GatewayVerification:
        if not publication.gateway_endpoint:
            raise AgentKitMcpError(
                "GATEWAY_ENDPOINT_MISSING",
                "Gateway endpoint is not available",
            )
        access_key, secret_key, session_token = self._credential_resolver()
        identity_client = _BoundIdentityClient(
            workload_identity=self._workload_identity,
            access_key=access_key,
            secret_key=secret_key,
            session_token=session_token,
            region=self._region,
        )
        toolset = VeIdentityMcpToolset(
            auth_config=oauth2_auth(
                provider_name=self._oauth_provider,
                scopes=self._scopes,
                auth_flow="M2M",
                identity_client=identity_client,
                region=self._region,
            ),
            connection_params=StreamableHTTPConnectionParams(
                url=publication.gateway_endpoint,
                timeout=self._timeout,
                sse_read_timeout=self._timeout,
            ),
        )
        context = _VerificationContext(self._workload_identity)
        try:
            tools = await toolset.get_tools(context)  # type: ignore[arg-type]
            mapping = {tool.name: tool for tool in tools}
            allowed = _resolve_tool(mapping, self._allowed_tool)
            if allowed is None:
                return GatewayVerification(
                    initialize_pass=True,
                    tools_list_pass=bool(tools),
                    allowed_call_pass=False,
                    denied_call_pass=False,
                    live_tools_count=len(tools),
                )
            allowed_result = await allowed.run_async(
                args=self._allowed_arguments,
                tool_context=context,  # type: ignore[arg-type]
            )
            credential = await toolset._get_credential(tool_context=context)
            session = await toolset._mcp_session_manager.create_session(
                headers=generate_headers(credential)
            )
            denied_result = await session.call_tool(
                self._denied_tool,
                arguments=self._denied_arguments,
            )
            return GatewayVerification(
                initialize_pass=True,
                tools_list_pass=True,
                allowed_call_pass=not _is_mcp_error(allowed_result),
                denied_call_pass=_is_expected_denial(
                    denied_result, self._denied_error_marker
                ),
                live_tools_count=len(tools),
                observed_version="2025-03-26+",
            )
        except AgentKitMcpError:
            raise
        except Exception as error:
            raise AgentKitMcpError(
                "GATEWAY_DATA_PLANE_FAILED",
                "Gateway data-plane verification failed",
                retryable=True,
            ) from error
        finally:
            await toolset.close()


def _json_object_env(name: str) -> dict[str, Any]:
    value = json.loads(os.getenv(name, "{}"))
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a JSON object")
    return value


def _resolve_tool(mapping: dict[str, Any], expected: str) -> Any | None:
    if expected in mapping:
        return mapping[expected]
    return next(
        (tool for name, tool in mapping.items() if name.endswith(expected)),
        None,
    )


def _is_mcp_error(result: Any) -> bool:
    if hasattr(result, "model_dump"):
        result = result.model_dump(by_alias=True, exclude_none=True)
    return bool(
        isinstance(result, dict)
        and (result.get("isError") is True or result.get("is_error") is True)
    )


def _is_expected_denial(result: Any, marker: str) -> bool:
    if hasattr(result, "model_dump"):
        result = result.model_dump(by_alias=True, exclude_none=True)
    if not _is_mcp_error(result):
        return False
    serialized = json.dumps(result, ensure_ascii=False).casefold()
    return marker.casefold() in serialized
