"""Concrete bounded adapters for REST, GraphQL, custom HTTP, and web discovery."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .http_transport import SecureHttpTransport, decode_json_rows, response_run_id
from .local_formats import _infer_mapping_fields, _SafeTextExtractor
from .models import (
    CapabilityReason,
    ConnectorOperation,
    DiscoveredField,
    DiscoveredResource,
)


@dataclass(frozen=True)
class HttpReadResult:
    source_locator: str
    raw_content: bytes
    rows: list[dict[str, object]]
    fields: list[tuple[str, str, bool]]
    media_type: str
    adapter_run_id: str
    checkpoint: dict[str, str]


class HttpSourceAdapter:
    CONNECTORS = frozenset({"rest_api", "graphql", "web_discovery", "custom_http"})

    def __init__(
        self,
        *,
        transport: SecureHttpTransport,
        secret_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._http = transport
        self._secret_resolver = secret_resolver or (lambda _ref: None)

    def discover(
        self,
        *,
        connector_key: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        trace_id: str,
    ) -> tuple[ConnectorOperation, HttpReadResult]:
        read = self.read(
            connector_key=connector_key,
            configuration=configuration,
            secret_ref=secret_ref,
            trace_id=trace_id,
        )
        name = self._operation_name(connector_key, configuration)
        resource = DiscoveredResource(
            id=self.resource_id(connector_key, name),
            name=name,
            resource_type="document"
            if connector_key == "web_discovery"
            else "operation",
            row_count=len(read.rows),
            fields=[
                DiscoveredField(name=field, data_type=data_type, nullable=nullable)
                for field, data_type, nullable in read.fields
            ],
        )
        return (
            ConnectorOperation(
                operation="discover",
                status="succeeded",
                trace_id=trace_id,
                reason=CapabilityReason(
                    code="HTTP_RESOURCE_DISCOVERED",
                    message="The configured endpoint returned a bounded, valid response.",
                ),
                resources=[resource],
            ),
            read,
        )

    def read(
        self,
        *,
        connector_key: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        trace_id: str,
    ) -> HttpReadResult:
        if connector_key not in self.CONNECTORS:
            raise ValueError("HTTP adapter does not support this connector")
        endpoint = configuration.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise ValueError("HTTP endpoint is required")
        timeout = _integer(configuration, "timeoutSeconds", 30, maximum=300)
        byte_limit = _integer(
            configuration,
            "maxResponseBytes",
            5 * 1024 * 1024,
            maximum=100 * 1024 * 1024,
        )
        row_limit = _integer(configuration, "maxRows", 10_000, maximum=1_000_000)
        rate_limit = _integer(configuration, "rateLimitPerMinute", 60, maximum=10_000)
        max_pages = _integer(configuration, "maxPages", 10, maximum=100)
        headers = self._authorization_headers(secret_ref)
        if connector_key == "graphql":
            query = configuration.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("GraphQL query is required")
            if re.search(r"\b(mutation|subscription)\b", query, re.IGNORECASE):
                raise ValueError("GraphQL connector accepts read-only queries")
            operation_name = _graphql_operation_name(query)
            allowlist = _operation_allowlist(configuration)
            if operation_name not in allowlist:
                raise ValueError("GraphQL operation is not on the configured allowlist")
            payload = self._http.request(
                method="POST",
                url=endpoint,
                trace_id=trace_id,
                timeout_seconds=timeout,
                max_response_bytes=byte_limit,
                rate_limit_per_minute=rate_limit,
                accepted_media_types={"application/json", "*+json"},
                headers=headers,
                json_body={"query": query, "variables": {}},
            )
            try:
                envelope = json.loads(payload.content)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("GraphQL response is not valid JSON") from error
            if not isinstance(envelope, dict) or envelope.get("errors"):
                raise ValueError("GraphQL response contains errors")
            rows = _rows_from_graphql(envelope.get("data"), max_rows=row_limit)
            return _result(endpoint, payload, rows)
        if connector_key == "web_discovery":
            if "page" not in _operation_allowlist(configuration):
                raise ValueError(
                    "web discovery operation is not on the configured allowlist"
                )
            payload = self._http.request(
                method="GET",
                url=endpoint,
                trace_id=trace_id,
                timeout_seconds=timeout,
                max_response_bytes=byte_limit,
                rate_limit_per_minute=rate_limit,
                accepted_media_types={"text/html", "text/plain"},
                headers=headers,
            )
            # The shared local-document extractor also strips executable and
            # styling elements. Decode here because this source is not a file.
            text = payload.content.decode("utf-8")
            if payload.media_type == "text/html":
                parser = _SafeTextExtractor()
                parser.feed(text)
                parser.close()
                text = "\n".join(
                    line.strip()
                    for line in "".join(parser.parts).splitlines()
                    if line.strip()
                )
            if not text.strip():
                raise ValueError("web discovery returned no readable text")
            rows = [{"text": line} for line in text.splitlines() if line.strip()]
            if len(rows) > row_limit:
                raise ValueError(
                    "web discovery response exceeds the configured row limit"
                )
            return _result(endpoint, payload, rows)

        method = (
            str(configuration.get("method", "GET")).upper()
            if connector_key == "custom_http"
            else "GET"
        )
        if method not in {"GET", "HEAD"}:
            raise ValueError("custom HTTP connector is read-only")
        operation_name = self._operation_name(connector_key, configuration)
        if operation_name not in _operation_allowlist(configuration):
            raise ValueError("HTTP operation is not on the configured allowlist")
        rows: list[dict[str, object]] = []
        raw_pages: list[bytes] = []
        current = endpoint
        last_payload = None
        pagination = str(configuration.get("paginationMode", "none"))
        for page in range(max_pages):
            page_url = _page_url(
                current,
                pagination=pagination,
                page=page,
                page_size=_integer(configuration, "pageSize", 100, maximum=10_000),
            )
            payload = self._http.request(
                method=method,
                url=page_url,
                trace_id=trace_id,
                timeout_seconds=timeout,
                max_response_bytes=max(byte_limit - sum(map(len, raw_pages)), 1),
                rate_limit_per_minute=rate_limit,
                accepted_media_types={"application/json", "*+json"},
                headers=headers,
            )
            last_payload = payload
            if method == "HEAD":
                rows = [
                    {
                        "status": payload.status_code,
                        "contentType": payload.media_type,
                        "etag": payload.headers.get("etag"),
                        "lastModified": payload.headers.get("last-modified"),
                    }
                ]
                raw_pages.append(payload.content)
                break
            page_rows, next_url = _json_page(payload, pagination=pagination)
            rows.extend(page_rows)
            raw_pages.append(payload.content)
            if len(rows) > row_limit:
                raise ValueError("HTTP response exceeds the configured row limit")
            if pagination == "none" or not next_url or not page_rows:
                break
            current = urljoin(payload.url, next_url)
        else:
            raise ValueError("HTTP pagination exceeds the configured page limit")
        if last_payload is None:
            raise ValueError("HTTP connector did not return a response")
        raw = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
        if len(raw) > byte_limit:
            raise ValueError("HTTP response exceeds the configured byte limit")
        return HttpReadResult(
            source_locator=endpoint,
            raw_content=raw,
            rows=rows,
            fields=_infer_mapping_fields(rows),
            media_type="application/json",
            adapter_run_id=response_run_id(last_payload),
            checkpoint=_checkpoint(last_payload),
        )

    @staticmethod
    def resource_id(connector_key: str, operation_name: str) -> str:
        digest = hashlib.sha256(
            f"{connector_key}:{operation_name}".encode()
        ).hexdigest()
        return f"http-resource-{digest[:24]}"

    @staticmethod
    def _operation_name(connector_key: str, configuration: Mapping[str, object]) -> str:
        if connector_key == "graphql":
            return _graphql_operation_name(str(configuration.get("query", "")))
        if connector_key == "web_discovery":
            return "page"
        return str(configuration.get("name") or "read")

    def _authorization_headers(self, secret_ref: str | None) -> dict[str, str]:
        if secret_ref is None:
            return {}
        value = self._secret_resolver(secret_ref)
        if value is None:
            raise PermissionError("HTTP connector secretRef could not be resolved")
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"Authorization": f"Bearer {value}"}
        if not isinstance(decoded, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in decoded.items()
        ):
            raise ValueError("HTTP connector secret must contain a string header map")
        return {str(key): str(item) for key, item in decoded.items()}


def _integer(
    configuration: Mapping[str, object],
    key: str,
    default: int,
    *,
    maximum: int,
) -> int:
    value = configuration.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise ValueError(f"HTTP {key} must be between 1 and {maximum}")
    return value


def _graphql_operation_name(query: str) -> str:
    match = re.search(r"\bquery\s+([_A-Za-z][_0-9A-Za-z]*)", query)
    return match.group(1) if match else "query"


def _operation_allowlist(configuration: Mapping[str, object]) -> list[str]:
    value = configuration.get("operationAllowlist")
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError("HTTP operation allowlist must not be empty")
    return list(dict.fromkeys(value))


def _rows_from_graphql(value: object, *, max_rows: int) -> list[dict[str, object]]:
    if isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    rows = value if isinstance(value, list) else [value]
    if len(rows) > max_rows:
        raise ValueError("GraphQL response exceeds the configured row limit")
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("GraphQL data must contain an object or array of objects")
        normalized.append({str(key): item for key, item in row.items()})
    return normalized


def _page_url(url: str, *, pagination: str, page: int, page_size: int) -> str:
    if pagination not in {"none", "offset", "cursor", "link_header"}:
        raise ValueError("HTTP pagination mode is unsupported")
    if pagination != "offset":
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"offset": str(page * page_size), "limit": str(page_size)})
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _json_page(
    payload, *, pagination: str
) -> tuple[list[dict[str, object]], str | None]:
    if pagination == "none":
        return decode_json_rows(payload, max_rows=1_000_000), None
    try:
        value = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("HTTP response is not valid JSON") from error
    if pagination == "link_header":
        rows = value if isinstance(value, list) else value.get("data")
        link = payload.headers.get("link", "")
        match = re.search(r'<([^>]+)>;\s*rel="?next"?', link)
        next_url = match.group(1) if match else None
    else:
        if not isinstance(value, dict):
            raise ValueError("paginated HTTP response must be an object")
        rows = value.get("data")
        next_url = value.get("next")
        if pagination == "cursor" and not next_url:
            cursor = value.get("nextCursor")
            if isinstance(cursor, str) and cursor:
                parts = urlsplit(payload.url)
                query = dict(parse_qsl(parts.query, keep_blank_values=True))
                query["cursor"] = cursor
                next_url = urlunsplit(
                    (
                        parts.scheme,
                        parts.netloc,
                        parts.path,
                        urlencode(query),
                        parts.fragment,
                    )
                )
    if not isinstance(rows, list) or not all(isinstance(item, dict) for item in rows):
        raise ValueError("paginated HTTP response data must be an array of objects")
    if next_url is not None and not isinstance(next_url, str):
        raise ValueError("HTTP pagination next reference must be a URL")
    return [{str(key): item for key, item in row.items()} for row in rows], next_url


def _result(endpoint: str, payload, rows: list[dict[str, object]]) -> HttpReadResult:
    return HttpReadResult(
        source_locator=endpoint,
        raw_content=payload.content,
        rows=rows,
        fields=_infer_mapping_fields(rows),
        media_type=payload.media_type,
        adapter_run_id=response_run_id(payload),
        checkpoint=_checkpoint(payload),
    )


def _checkpoint(payload) -> dict[str, str]:
    return {
        key: value
        for key, value in payload.headers.items()
        if key in {"etag", "last-modified"}
    }
