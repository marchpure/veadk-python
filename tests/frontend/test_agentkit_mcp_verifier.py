from __future__ import annotations

import json

from frontend.server.extensions.agentkit_mcp.verifier import (
    IdentityM2MGatewayVerifier,
    _is_expected_denial,
)


def test_expected_denial_requires_explicit_policy_marker() -> None:
    denied = {
        "isError": True,
        "content": [{"type": "text", "text": "ACTION_NOT_ALLOWED by token policy"}],
    }
    unrelated = {
        "isError": True,
        "content": [{"type": "text", "text": "upstream timeout"}],
    }

    assert _is_expected_denial(denied, "ACTION_NOT_ALLOWED") is True
    assert _is_expected_denial(unrelated, "ACTION_NOT_ALLOWED") is False
    assert _is_expected_denial({"isError": False}, "ACTION_NOT_ALLOWED") is False


def test_live_verifier_requires_complete_environment(monkeypatch) -> None:
    keys = (
        "DATA_WORKSHOP_MCP_VERIFY_WORKLOAD_IDENTITY",
        "DATA_WORKSHOP_MCP_VERIFY_OAUTH_PROVIDER",
        "DATA_WORKSHOP_MCP_VERIFY_ALLOWED_TOOL",
        "DATA_WORKSHOP_MCP_VERIFY_DENIED_TOOL",
        "DATA_WORKSHOP_MCP_VERIFY_DENIED_ERROR_MARKER",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    assert (
        IdentityM2MGatewayVerifier.from_env(
            credential_resolver=lambda: ("ak", "sk", None),
            region="cn-beijing",
        )
        is None
    )


def test_live_verifier_parses_non_secret_action_configuration(monkeypatch) -> None:
    values = {
        "DATA_WORKSHOP_MCP_VERIFY_WORKLOAD_IDENTITY": "workload-1",
        "DATA_WORKSHOP_MCP_VERIFY_OAUTH_PROVIDER": "provider-1",
        "DATA_WORKSHOP_MCP_VERIFY_ALLOWED_TOOL": "allowed_action",
        "DATA_WORKSHOP_MCP_VERIFY_ALLOWED_ARGUMENTS": json.dumps({"limit": 1}),
        "DATA_WORKSHOP_MCP_VERIFY_DENIED_TOOL": "denied_action",
        "DATA_WORKSHOP_MCP_VERIFY_DENIED_ARGUMENTS": json.dumps({"value": "x"}),
        "DATA_WORKSHOP_MCP_VERIFY_DENIED_ERROR_MARKER": "ACTION_NOT_ALLOWED",
        "DATA_WORKSHOP_MCP_VERIFY_UNAUTHORIZED_WORKLOAD_IDENTITY": "workload-denied",
        "DATA_WORKSHOP_MCP_VERIFY_UNAUTHORIZED_ERROR_MARKER": "CLIENT_NOT_ALLOWED",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    verifier = IdentityM2MGatewayVerifier.from_env(
        credential_resolver=lambda: ("ak", "sk", None),
        region="cn-beijing",
    )

    assert verifier is not None
    assert verifier._allowed_arguments == {"limit": 1}
    assert verifier._denied_arguments == {"value": "x"}
    assert verifier._denied_error_marker == "ACTION_NOT_ALLOWED"
