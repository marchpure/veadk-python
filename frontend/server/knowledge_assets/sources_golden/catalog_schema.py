"""Reusable schema builders for the connector catalog."""

from __future__ import annotations

from .models import (
    CapabilityReason,
    CapabilityState,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorPermission,
    FormField,
    FormFieldType,
    FormSchema,
    SyncMode,
)


def field(
    field_type: FormFieldType,
    title: str,
    *,
    required: bool = False,
    description: str = "",
    default: str | int | bool | list[str] | None = None,
    options: list[str] | None = None,
    secret_reference: bool = False,
) -> FormField:
    return FormField(
        type=field_type,
        title=title,
        required=required,
        description=description,
        default=default,
        options=options or [],
        secret_reference=secret_reference,
    )


def schema(**fields: FormField) -> FormSchema:
    return FormSchema(
        properties=fields,
        required=[key for key, value in fields.items() if value.required],
    )


EMPTY_SCHEMA = FormSchema(properties={})
SECRET_REF_SCHEMA = schema(
    secretRef=field(
        "string",
        "Secret reference",
        required=True,
        description="Reference in the server-side secret store (secret://…), never a value.",
        secret_reference=True,
    )
)
OPTIONAL_SECRET_REF_SCHEMA = schema(
    secretRef=field(
        "string",
        "Secret reference",
        description="Optional server-side authorization header secret reference.",
        secret_reference=True,
    )
)


def reason(state: CapabilityState, code: str | None = None) -> CapabilityReason:
    defaults = {
        "available": (
            "AVAILABLE",
            "This connector has a formal adapter and durable lifecycle.",
        ),
        "configurable": (
            "CONFIG_REQUIRED",
            "A definition can be configured, but no provider result is claimed.",
        ),
        "credential_blocked": (
            "CREDENTIAL_REQUIRED",
            "A real provider adapter contract exists; usable secretRef/configuration is required.",
        ),
        "unsupported": (
            "ADAPTER_NOT_IMPLEMENTED",
            "The catalog entry is visible, but no production adapter is implemented.",
        ),
    }
    default_code, message = defaults[state]
    return CapabilityReason(code=code or default_code, message=message)


def permission_policy(
    *,
    provider_scopes: list[str] | None = None,
    inherits_source_acl: bool = False,
) -> ConnectorPermission:
    return ConnectorPermission(
        read_scopes=["workspace.member", "source.read"],
        manage_scopes=["workspace.member", "source.write"],
        provider_scopes=provider_scopes or [],
        inherits_source_acl=inherits_source_acl,
    )


def definition(
    key: str,
    category: ConnectorCategory,
    name: str,
    description: str,
    capabilities: list[str],
    state: CapabilityState,
    input_schema: FormSchema,
    credential_schema: FormSchema = EMPTY_SCHEMA,
    discovery_modes: list[str] | None = None,
    sync_modes: list[SyncMode] | None = None,
    permissions: ConnectorPermission | None = None,
    reason_code: str | None = None,
) -> ConnectorDefinition:
    execution_properties = dict(input_schema.properties)
    execution_properties.setdefault(
        "maxAttempts",
        field(
            "integer",
            "Maximum retry attempts",
            default=1,
            description="1–5; retries only typed transient failures.",
        ),
    )
    input_schema = input_schema.model_copy(update={"properties": execution_properties})
    return ConnectorDefinition(
        connector_key=key,
        category=category,
        name=name,
        description=description,
        capabilities=capabilities,
        capability_state=state,
        input_schema=input_schema,
        credential_schema=credential_schema,
        discovery_modes=discovery_modes or ["validate", "discover", "introspect"],
        sync_modes=sync_modes or ["incremental"],
        permissions=permissions or permission_policy(),
        reason=reason(state, reason_code),
    )
