# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Authoritative connector registry for the Knowledge Asset workbench."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, TypedDict


ConnectorCategory = Literal["document", "database", "local", "saas", "mcp", "custom"]
ConnectorAvailability = Literal[
    "available",
    "needs_auth",
    "needs_helper",
    "preview",
    "planned",
    "unsupported",
]


class ConnectorDefinition(TypedDict):
    id: str
    version: str
    display_name: str
    category: ConnectorCategory
    availability: ConnectorAvailability
    auth_modes: list[str]
    required_scopes: list[str]
    capabilities: list[str]
    form_schema: dict[str, Any]
    resource_picker_schema: dict[str, Any]
    safety_notice: str
    help_text: str


_CONNECTORS: tuple[ConnectorDefinition, ...] = (
    {
        "id": "file",
        "version": "1.0.0",
        "display_name": "File",
        "category": "document",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "retrieval_index"],
        "form_schema": {
            "groups": [
                {
                    "id": "upload",
                    "label": "Upload",
                    "fields": ["name", "file", "content"],
                }
            ],
            "accepted_file_types": [
                ".md",
                ".markdown",
                ".txt",
                ".json",
                ".csv",
                ".pdf",
                "image/*",
            ],
            "max_bytes": 8 * 1024 * 1024,
        },
        "resource_picker_schema": {
            "mode": "single_upload",
            "selection_types": ["file", "pdf", "image"],
            "supports_search": False,
        },
        "safety_notice": "Files are scanned for browser credentials before import; do not upload cookies, Authorization headers, or tokens.",
        "help_text": "Upload a local document or paste cleaned text and send it through the existing Studio knowledge import path.",
    },
    {
        "id": "text",
        "version": "1.0.0",
        "display_name": "Text",
        "category": "document",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "retrieval_index"],
        "form_schema": {
            "groups": [
                {"id": "content", "label": "Content", "fields": ["name", "content"]}
            ],
            "content_formats": ["markdown", "text"],
            "max_bytes": 2 * 1024 * 1024,
        },
        "resource_picker_schema": {
            "mode": "single_document",
            "selection_types": ["text"],
            "supports_search": False,
        },
        "safety_notice": "Only cleaned text is accepted; pasted credentials are rejected by the backend.",
        "help_text": "Paste Markdown or plain text to create a first-class source resource.",
    },
    {
        "id": "pdf",
        "version": "1.0.0",
        "display_name": "PDF",
        "category": "document",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "retrieval_index"],
        "form_schema": {
            "groups": [
                {
                    "id": "upload",
                    "label": "Upload",
                    "fields": ["name", "file", "content"],
                }
            ],
            "accepted_file_types": [".pdf", "application/pdf"],
            "max_bytes": 8 * 1024 * 1024,
        },
        "resource_picker_schema": {
            "mode": "single_upload",
            "selection_types": ["pdf"],
            "supports_search": False,
        },
        "safety_notice": "PDF uploads use the existing Studio import path and do not accept embedded browser credentials.",
        "help_text": "Upload a PDF or paste extracted Markdown when OCR/extraction has already happened locally.",
    },
    {
        "id": "image",
        "version": "1.0.0",
        "display_name": "Image",
        "category": "document",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "retrieval_index"],
        "form_schema": {
            "groups": [
                {
                    "id": "upload",
                    "label": "Upload",
                    "fields": ["name", "file", "content"],
                }
            ],
            "accepted_file_types": ["image/*"],
            "max_bytes": 8 * 1024 * 1024,
        },
        "resource_picker_schema": {
            "mode": "single_upload",
            "selection_types": ["image"],
            "supports_search": False,
        },
        "safety_notice": "Image files are registered through the same controlled upload path; raw browser session data is rejected.",
        "help_text": "Register images now and keep their OCR/indexing metadata under one source resource.",
    },
    {
        "id": "web",
        "version": "1.0.0",
        "display_name": "Public Web Page",
        "category": "document",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "sync", "retrieval_index"],
        "form_schema": {
            "groups": [
                {"id": "url", "label": "Public URL", "fields": ["name", "uri"]}
            ],
            "uri_schemes": ["https", "http"],
        },
        "resource_picker_schema": {
            "mode": "url",
            "selection_types": ["web_page"],
            "supports_search": False,
        },
        "safety_notice": "The server applies SSRF checks, redirect validation, response size limits, and secret redaction before import.",
        "help_text": "Import public documentation pages without sending cookies or browser profile data.",
    },
    {
        "id": "local_web",
        "version": "1.0.0",
        "display_name": "Local Web Capture",
        "category": "local",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "retrieval_index"],
        "form_schema": {
            "groups": [
                {
                    "id": "cleaned_content",
                    "label": "Cleaned content",
                    "fields": ["name", "uri", "content"],
                }
            ],
            "content_formats": ["markdown", "html"],
        },
        "resource_picker_schema": {
            "mode": "manual_capture",
            "selection_types": ["local_web_page"],
            "supports_search": False,
        },
        "safety_notice": "Only user-cleaned page content is accepted; cookies, local storage, and browser profiles are never stored.",
        "help_text": "Capture pages that require a local session by pasting cleaned content from the browser.",
    },
    {
        "id": "intranet_web",
        "version": "1.0.0",
        "display_name": "Intranet Page",
        "category": "local",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "retrieval_index"],
        "form_schema": {
            "groups": [
                {
                    "id": "cleaned_content",
                    "label": "Cleaned content",
                    "fields": ["name", "uri", "content"],
                }
            ],
            "content_formats": ["markdown", "html"],
        },
        "resource_picker_schema": {
            "mode": "manual_capture",
            "selection_types": ["intranet_web_page"],
            "supports_search": False,
        },
        "safety_notice": "The backend stores only sanitized content supplied by the user; no intranet cookies or session headers are accepted.",
        "help_text": "Register intranet pages as private source resources after manual cleanup.",
    },
    {
        "id": "schema_snapshot",
        "version": "1.0.0",
        "display_name": "Schema Snapshot",
        "category": "database",
        "availability": "available",
        "auth_modes": ["none"],
        "required_scopes": [],
        "capabilities": ["import_resource", "schema_introspection", "semantic_build"],
        "form_schema": {
            "groups": [
                {"id": "schema", "label": "Schema JSON", "fields": ["name", "schema"]}
            ],
            "accepted_shapes": ["models", "tables", "fields", "columns", "metrics"],
        },
        "resource_picker_schema": {
            "mode": "schema_payload",
            "selection_types": ["database_schema", "database_table", "database_view"],
            "supports_search": False,
        },
        "safety_notice": "Upload metadata only. Do not include row samples, credentials, DSNs, or unrestricted SQL.",
        "help_text": "Register a DuckDB/Wren-style schema payload as the seed for Semantic Skill generation.",
    },
    {
        "id": "feishu_doc",
        "version": "1.0.0",
        "display_name": "Feishu Document",
        "category": "saas",
        "availability": "needs_auth",
        "auth_modes": ["oauth"],
        "required_scopes": ["docs:doc:readonly", "wiki:wiki:readonly"],
        "capabilities": ["list_resources", "import_resource", "sync", "retrieval_index"],
        "form_schema": {
            "groups": [
                {"id": "document", "label": "Document", "fields": ["name", "uri"]}
            ],
            "uri_hosts": ["feishu.cn", "larksuite.com", "larkoffice.com"],
        },
        "resource_picker_schema": {
            "mode": "provider_picker",
            "selection_types": ["feishu_doc", "feishu_sheet"],
            "supports_search": True,
        },
        "safety_notice": "OAuth must be configured before import; the workbench must not simulate a successful document sync.",
        "help_text": "Connect Feishu with OAuth, then import selected documents with source permissions preserved.",
    },
    {
        "id": "postgres",
        "version": "1.0.0",
        "display_name": "PostgreSQL",
        "category": "database",
        "availability": "preview",
        "auth_modes": ["password", "iam"],
        "required_scopes": [],
        "capabilities": ["list_resources", "schema_introspection", "semantic_build"],
        "form_schema": {
            "groups": [
                {
                    "id": "endpoint",
                    "label": "Endpoint",
                    "fields": ["host", "port", "database", "ssl_mode"],
                },
                {
                    "id": "credential",
                    "label": "Credential",
                    "fields": ["username", "password"],
                },
            ],
            "secret_fields": ["password", "ssl_key"],
        },
        "resource_picker_schema": {
            "mode": "tree",
            "page_size": 100,
            "supports_search": True,
            "selection_types": [
                "database_schema",
                "database_table",
                "database_view",
            ],
        },
        "safety_notice": "The Phase 1 manifest is present, but live connection requires credential vault configuration and a read-only account.",
        "help_text": "Register now as a needs-configuration connection; schema introspection will use the backend connector once configured.",
    },
    {
        "id": "mysql",
        "version": "1.0.0",
        "display_name": "MySQL",
        "category": "database",
        "availability": "preview",
        "auth_modes": ["password"],
        "required_scopes": [],
        "capabilities": ["list_resources", "schema_introspection", "semantic_build"],
        "form_schema": {
            "groups": [
                {
                    "id": "endpoint",
                    "label": "Endpoint",
                    "fields": ["host", "port", "database", "ssl_mode"],
                },
                {
                    "id": "credential",
                    "label": "Credential",
                    "fields": ["username", "password"],
                },
            ],
            "secret_fields": ["password"],
        },
        "resource_picker_schema": {
            "mode": "tree",
            "page_size": 100,
            "supports_search": True,
            "selection_types": [
                "database_schema",
                "database_table",
                "database_view",
            ],
        },
        "safety_notice": "The Phase 1 manifest is present, but live connection requires credential vault configuration and a read-only account.",
        "help_text": "Register now as a needs-configuration connection; schema introspection will use the backend connector once configured.",
    },
    {
        "id": "oracle",
        "version": "1.0.0",
        "display_name": "Oracle",
        "category": "database",
        "availability": "preview",
        "auth_modes": ["password"],
        "required_scopes": [],
        "capabilities": ["list_resources", "schema_introspection", "semantic_build"],
        "form_schema": {
            "groups": [
                {
                    "id": "endpoint",
                    "label": "Endpoint",
                    "fields": ["host", "port", "service_name"],
                },
                {
                    "id": "credential",
                    "label": "Credential",
                    "fields": ["username", "password"],
                },
            ],
            "secret_fields": ["password"],
        },
        "resource_picker_schema": {
            "mode": "tree",
            "page_size": 100,
            "supports_search": True,
            "selection_types": [
                "database_schema",
                "database_table",
                "database_view",
            ],
        },
        "safety_notice": "The Phase 1 manifest is present, but live connection requires credential vault configuration and a read-only account.",
        "help_text": "Register now as a needs-configuration connection; schema introspection will use the backend connector once configured.",
    },
    {
        "id": "saas_dlt",
        "version": "0.1.0",
        "display_name": "SaaS / dlt",
        "category": "saas",
        "availability": "planned",
        "auth_modes": ["oauth", "api_key"],
        "required_scopes": [],
        "capabilities": ["list_resources", "sync"],
        "form_schema": {"groups": []},
        "resource_picker_schema": {
            "mode": "provider_picker",
            "selection_types": [],
            "supports_search": True,
        },
        "safety_notice": "Not available in the Phase 1 local connector slice.",
        "help_text": "Planned connector family for SaaS pipelines powered by dlt-style extraction.",
    },
    {
        "id": "mcp",
        "version": "0.1.0",
        "display_name": "MCP Connector",
        "category": "mcp",
        "availability": "planned",
        "auth_modes": ["service_account", "none"],
        "required_scopes": [],
        "capabilities": ["list_resources", "import_resource"],
        "form_schema": {"groups": []},
        "resource_picker_schema": {
            "mode": "tool_manifest",
            "selection_types": [],
            "supports_search": False,
        },
        "safety_notice": "MCP tools are not invoked by the Phase 1 registry.",
        "help_text": "Future connector surface for signed MCP resource providers.",
    },
    {
        "id": "custom_rest",
        "version": "0.1.0",
        "display_name": "Custom REST / OpenAPI",
        "category": "custom",
        "availability": "planned",
        "auth_modes": ["api_key", "oauth", "none"],
        "required_scopes": [],
        "capabilities": ["list_resources", "import_resource", "sync"],
        "form_schema": {"groups": []},
        "resource_picker_schema": {
            "mode": "openapi",
            "selection_types": [],
            "supports_search": False,
        },
        "safety_notice": "Custom executable connector plugins are not loaded by Phase 1.",
        "help_text": "Planned signed-extension path for REST and OpenAPI providers.",
    },
)


def list_connector_definitions(
    *,
    category: str | None = None,
) -> list[ConnectorDefinition]:
    """Return redaction-safe connector manifests for frontend rendering."""

    items: list[ConnectorDefinition] = []
    normalized_category = (category or "").strip().casefold()
    for connector in _CONNECTORS:
        if normalized_category and connector["category"] != normalized_category:
            continue
        items.append(deepcopy(connector))
    return items


def get_connector_definition(connector_id: str) -> ConnectorDefinition:
    normalized = connector_id.strip().casefold()
    for connector in _CONNECTORS:
        if connector["id"] == normalized:
            return deepcopy(connector)
    raise KeyError(connector_id)


__all__ = [
    "ConnectorAvailability",
    "ConnectorCategory",
    "ConnectorDefinition",
    "get_connector_definition",
    "list_connector_definitions",
]
