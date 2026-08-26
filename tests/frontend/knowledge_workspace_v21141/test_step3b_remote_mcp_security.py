from __future__ import annotations

import httpx
import pytest

from frontend.server.knowledge_assets.sources_golden.mcp_remote import (
    RemoteMcpClient,
    RemoteMcpError,
)


def _configuration(**overrides: object) -> dict[str, object]:
    return {
        "transport": "streamable_http",
        "endpoint": "https://mcp.example/rpc",
        "toolAllowlist": ["inventory.read"],
        "startupTimeoutSeconds": 1,
        "callTimeoutSeconds": 1,
        "maxPages": 2,
        "outputBytes": 10_000,
        **overrides,
    }


def test_unresolvable_remote_mcp_credential_has_typed_redacted_trace() -> None:
    secret_ref = "secret://workspace-step3b/missing-token"
    client = RemoteMcpClient(
        secret_resolver=lambda _ref: None,
        resolver=lambda _host: ["93.184.216.34"],
    )

    with pytest.raises(RemoteMcpError) as failure:
        client.discover(
            workspace_id="workspace-step3b",
            principal_id="user-step3b",
            connection_id="connection-step3b",
            configuration=_configuration(),
            secret_ref=secret_ref,
            trace_id="trace-missing-credential",
        )

    assert failure.value.code == "MCP_AUTHENTICATION_FAILED"
    assert failure.value.trace.status == "failed"
    assert failure.value.trace.error_code == "MCP_AUTHENTICATION_FAILED"
    assert failure.value.trace.exchanges[-1].method == "initialize"
    assert secret_ref not in str(failure.value)
    assert secret_ref not in failure.value.trace.model_dump_json()


def test_remote_mcp_rejected_credential_has_typed_failed_trace() -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer wrong-token"
        return httpx.Response(401, json={"error": "invalid token"})

    client = RemoteMcpClient(
        secret_resolver=lambda _ref: "wrong-token",
        resolver=lambda _host: ["93.184.216.34"],
        transport=httpx.MockTransport(reject),
    )

    with pytest.raises(RemoteMcpError) as failure:
        client.discover(
            workspace_id="workspace-step3b",
            principal_id="user-step3b",
            connection_id="connection-step3b",
            configuration=_configuration(),
            secret_ref="secret://workspace-step3b/mcp-token",
            trace_id="trace-rejected-credential",
        )

    assert failure.value.code == "MCP_AUTHENTICATION_FAILED"
    assert failure.value.trace.status == "failed"
    assert failure.value.trace.error_code == "MCP_AUTHENTICATION_FAILED"


def test_remote_mcp_redirect_is_rejected_with_typed_failed_trace() -> None:
    client = RemoteMcpClient(
        resolver=lambda _host: ["93.184.216.34"],
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                307,
                headers={"Location": "https://other.example/mcp"},
            )
        ),
    )

    with pytest.raises(RemoteMcpError) as failure:
        client.discover(
            workspace_id="workspace-step3b",
            principal_id="user-step3b",
            connection_id="connection-step3b",
            configuration=_configuration(),
            secret_ref=None,
            trace_id="trace-redirect",
        )

    assert failure.value.code == "MCP_REDIRECT_FORBIDDEN"
    assert failure.value.trace.error_code == "MCP_REDIRECT_FORBIDDEN"


def test_remote_mcp_rejects_dns_rebinding_before_protocol_exchange() -> None:
    resolutions = iter(
        [
            ["93.184.216.34"],
            ["8.8.8.8"],
        ]
    )
    client = RemoteMcpClient(
        resolver=lambda _host: next(resolutions),
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(RemoteMcpError) as failure:
        client.discover(
            workspace_id="workspace-step3b",
            principal_id="user-step3b",
            connection_id="connection-step3b",
            configuration=_configuration(),
            secret_ref=None,
            trace_id="trace-dns-rebinding",
        )

    assert failure.value.code == "MCP_DNS_REBINDING"
    assert failure.value.trace.error_code == "MCP_DNS_REBINDING"


def test_remote_mcp_timeout_has_typed_timed_out_trace() -> None:
    client = RemoteMcpClient(
        resolver=lambda _host: ["93.184.216.34"],
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(
                httpx.ReadTimeout("deadline exceeded", request=request)
            )
        ),
    )

    with pytest.raises(RemoteMcpError) as failure:
        client.discover(
            workspace_id="workspace-step3b",
            principal_id="user-step3b",
            connection_id="connection-step3b",
            configuration=_configuration(),
            secret_ref=None,
            trace_id="trace-timeout",
        )

    assert failure.value.code == "MCP_TIMEOUT"
    assert failure.value.trace.status == "timed_out"
    assert failure.value.trace.error_code == "MCP_TIMEOUT"
