"""Bounded HTTP transport shared by network-backed connector adapters."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from urllib.parse import urljoin, urlparse

import httpx


@dataclass(frozen=True)
class HttpPayload:
    url: str
    status_code: int
    media_type: str
    content: bytes
    headers: dict[str, str]
    trace_id: str


class SecureHttpTransport:
    """HTTP client that keeps redirects, DNS, MIME, rate and byte budgets explicit."""

    def __init__(
        self,
        *,
        resolver: Callable[[str], list[str]] | None = None,
        allow_private_hosts: set[str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        self._allow_private_hosts = frozenset(allow_private_hosts or ())
        self._transport = transport
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._rate_lock = RLock()

    def request(
        self,
        *,
        method: str,
        url: str,
        trace_id: str,
        timeout_seconds: float,
        max_response_bytes: int,
        rate_limit_per_minute: int,
        accepted_media_types: set[str],
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
        max_redirects: int = 3,
    ) -> HttpPayload:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD", "POST"}:
            raise ValueError("HTTP connector method is not allowed")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("HTTP timeout must be between 0 and 300 seconds")
        if max_response_bytes < 1 or max_response_bytes > 100 * 1024 * 1024:
            raise ValueError("HTTP response byte limit is invalid")
        if rate_limit_per_minute < 1 or rate_limit_per_minute > 10_000:
            raise ValueError("HTTP rate limit is invalid")
        current_url = url
        safe_headers = {
            str(key): str(value)
            for key, value in (headers or {}).items()
            if str(key).casefold()
            not in {"host", "content-length", "transfer-encoding", "connection"}
        }
        with httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
            trust_env=False,
            transport=self._transport,
        ) as client:
            for redirect_count in range(max_redirects + 1):
                addresses = frozenset(
                    _validate_endpoint(
                        current_url,
                        resolver=self._resolver,
                        allow_private_hosts=self._allow_private_hosts,
                    )
                )
                self._consume_rate_budget(current_url, rate_limit_per_minute)
                try:
                    with client.stream(
                        normalized_method,
                        current_url,
                        headers=safe_headers,
                        json=json_body,
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirect_count >= max_redirects:
                                raise ValueError("HTTP redirect limit exceeded")
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("HTTP redirect has no Location header")
                            redirected_url = urljoin(current_url, location)
                            if _origin(redirected_url) != _origin(current_url):
                                raise ValueError(
                                    "HTTP cross-origin redirects are not allowed"
                                )
                            current_url = redirected_url
                            continue
                        response.raise_for_status()
                        media_type = (
                            response.headers.get("content-type", "")
                            .split(";", 1)[0]
                            .strip()
                            .casefold()
                        )
                        if not media_type or not any(
                            media_type == accepted
                            or accepted.endswith("/*")
                            and media_type.startswith(accepted[:-1])
                            or accepted.startswith("*+")
                            and media_type.endswith(accepted[1:])
                            for accepted in accepted_media_types
                        ):
                            raise ValueError(
                                f"HTTP response content type is not allowed: {media_type or 'missing'}"
                            )
                        content = bytearray()
                        if normalized_method != "HEAD":
                            for chunk in response.iter_bytes():
                                content.extend(chunk)
                                if len(content) > max_response_bytes:
                                    raise ValueError(
                                        "HTTP response exceeds the configured byte limit"
                                    )
                        final_addresses = frozenset(
                            _validate_endpoint(
                                current_url,
                                resolver=self._resolver,
                                allow_private_hosts=self._allow_private_hosts,
                            )
                        )
                        if final_addresses != addresses:
                            raise ValueError(
                                "HTTP endpoint DNS resolution changed during the request"
                            )
                        return HttpPayload(
                            url=current_url,
                            status_code=response.status_code,
                            media_type=media_type,
                            content=bytes(content),
                            headers={
                                key.casefold(): value
                                for key, value in response.headers.items()
                                if key.casefold()
                                in {
                                    "content-type",
                                    "etag",
                                    "last-modified",
                                    "retry-after",
                                    "link",
                                }
                            },
                            trace_id=trace_id,
                        )
                except httpx.TimeoutException as error:
                    raise TimeoutError("HTTP connector request timed out") from error
                except httpx.HTTPStatusError as error:
                    if error.response.status_code == 429:
                        raise ValueError("HTTP connector was rate limited") from error
                    raise ValueError(
                        f"HTTP connector returned status {error.response.status_code}"
                    ) from error
        raise ValueError("HTTP connector did not produce a response")

    def _consume_rate_budget(self, url: str, limit: int) -> None:
        host = urlparse(url).hostname or ""
        now = time.monotonic()
        with self._rate_lock:
            requests = self._requests[host]
            while requests and now - requests[0] >= 60:
                requests.popleft()
            if len(requests) >= limit:
                raise ValueError("HTTP connector local rate limit exceeded")
            requests.append(now)


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), parsed.port


def network_origin(url: str) -> tuple[str, str, int | None]:
    """Return the normalized origin used by connector redirect guards."""
    return _origin(url)


def validate_network_endpoint(
    endpoint: str,
    *,
    resolver: Callable[[str], list[str]] | None = None,
    allow_private_hosts: set[str] | frozenset[str] | None = None,
) -> frozenset[str]:
    """Validate one network endpoint and return its pinned DNS answer set."""
    return frozenset(
        _validate_endpoint(
            endpoint,
            resolver=resolver,
            allow_private_hosts=frozenset(allow_private_hosts or ()),
        )
    )


def _validate_endpoint(
    endpoint: str,
    *,
    resolver: Callable[[str], list[str]] | None,
    allow_private_hosts: frozenset[str],
) -> list[str]:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Web/API endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("Web/API endpoint must not contain inline credentials")
    addresses = (
        resolver(parsed.hostname)
        if resolver
        else [
            str(address)
            for address in {
                item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)
            }
        ]
    )
    if not addresses:
        raise ValueError("Web/API endpoint did not resolve to an address")
    private_allowed = parsed.hostname in allow_private_hosts
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not private_allowed and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("Web/API endpoint resolves to a non-public address")
    return addresses


def decode_json_rows(payload: HttpPayload, *, max_rows: int) -> list[dict[str, object]]:
    try:
        value = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("HTTP response is not valid JSON") from error
    rows = value if isinstance(value, list) else [value]
    if len(rows) > max_rows:
        raise ValueError("HTTP response exceeds the configured row limit")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("HTTP response must be an object or array of objects")
    return [{str(key): item for key, item in row.items()} for row in rows]


def response_run_id(payload: HttpPayload) -> str:
    digest = hashlib.sha256(
        (
            f"{payload.trace_id}:{payload.url}:{payload.status_code}:"
            f"{hashlib.sha256(payload.content).hexdigest()}"
        ).encode()
    ).hexdigest()
    return f"http-run-{digest[:24]}"
