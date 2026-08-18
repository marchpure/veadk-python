"""Typed REST-only tool for the packaged Byaan Semantic Skill.

This helper intentionally has no database driver or credential fields. Runtime
secrets are supplied through environment variables by the generated Agent.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

QUERY_URL = '/api/external/assets/semantic_model/9172f615-8b39-4280-81a6-9ca14cfc0be5/query'
METRICS = ['ticket_count']
DIMENSIONS = ['store', 'sell_date', 'sell_state', 'sell_type']


def _datastudio_query_url(path_or_url: str) -> str:
    base = os.environ["DATASTUDIO_BASE_URL"].rstrip("/")
    parsed_base = urlparse(base)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
        raise ValueError("DATASTUDIO_BASE_URL must be an http(s) URL")
    candidate = (path_or_url or "").strip()
    if candidate.startswith("/"):
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme or parsed_candidate.netloc:
            raise ValueError("Data Studio query URL must not be protocol-relative")
        url = urljoin(f"{base}/", candidate.lstrip("/"))
    else:
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme not in {"http", "https"} or not parsed_candidate.netloc:
            raise ValueError("Data Studio query URL must be relative or http(s)")
        if parsed_candidate.scheme != parsed_base.scheme or parsed_candidate.netloc != parsed_base.netloc:
            raise ValueError("Data Studio query URL origin does not match DATASTUDIO_BASE_URL")
        url = candidate
    parsed_url = urlparse(url)
    if parsed_url.scheme != parsed_base.scheme or parsed_url.netloc != parsed_base.netloc:
        raise ValueError("Data Studio query URL origin does not match DATASTUDIO_BASE_URL")
    if not parsed_url.path.startswith("/api/external/assets/"):
        raise ValueError("Data Studio query URL must target /api/external/assets")
    return url


def query_semantic_metric(
    metric: str,
    dimension: str | None = None,
    grain: str | None = None,
    filters: dict[str, Any] | None = None,
    time_range: dict[str, Any] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query Oracle Sales Semantic Model session-h-oracle-20260818145458 through Data Studio REST.

    Use exact metric ids/names from the packaged MDL: ticket_count.
    Use exact dimension ids/names from the packaged MDL: store, sell_date, sell_state, sell_type.
    """
    payload = {
        "metric": metric,
        "dimension": dimension,
        "grain": grain,
        "filters": filters or {},
        "time_range": time_range or {},
        "limit": limit,
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    response = requests.post(
        _datastudio_query_url(QUERY_URL),
        json=payload,
        headers={"Authorization": f"Bearer {os.environ['BYAAN_MCP_API_KEY']}"},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("data", body) if isinstance(body, dict) else {"data": body}
