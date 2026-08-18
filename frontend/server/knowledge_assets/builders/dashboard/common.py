"""Shared helpers for native AskData and Dashboard Skill builders."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from ...service import KnowledgeAssetServiceError, redact_sensitive

_IDENTIFIER_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_PII_RE = re.compile(
    r"(customer|cust|contact|phone|tel|mobile|email|address|addr|passport|"
    r"idcard|identity|member[_-]?card|buyer|recipient|consignee)",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_slug(value: str, fallback: str = "asset") -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().casefold())
    slug = re.sub(r"-{2,}", "-", slug).strip("-._")
    return slug[:96] or f"{fallback}-{hashlib.sha256(value.encode()).hexdigest()[:8]}"


def safe_identifier(value: Any, *, fallback: str = "field") -> str:
    text = _IDENTIFIER_RE.sub("_", str(value or "").strip()).strip("._-")
    return text[:128] or fallback


def first_mapping(items: Any, key: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    normalized = key.casefold()
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates = [
            item.get("id"),
            item.get("slug"),
            item.get("name"),
            item.get("field"),
            item.get("businessName"),
            item.get("business_name"),
        ]
        if any(str(candidate or "").casefold() == normalized for candidate in candidates):
            return item
    return None


def metric_id(metric: dict[str, Any]) -> str:
    return safe_identifier(
        metric.get("id")
        or metric.get("slug")
        or metric.get("name")
        or metric.get("businessName")
        or metric.get("business_name"),
        fallback="metric",
    )


def metric_label(metric: dict[str, Any]) -> str:
    return str(
        metric.get("businessName")
        or metric.get("business_name")
        or metric.get("name")
        or metric_id(metric)
    )


def metric_definition(metric: dict[str, Any]) -> str:
    return str(
        metric.get("definition")
        or metric.get("description")
        or metric.get("formula")
        or metric_label(metric)
    )


def dimension_id(dimension: dict[str, Any]) -> str:
    return safe_identifier(
        dimension.get("id")
        or dimension.get("slug")
        or dimension.get("field")
        or dimension.get("name"),
        fallback="dimension",
    )


def dimension_label(dimension: dict[str, Any]) -> str:
    return str(dimension.get("name") or dimension.get("field") or dimension_id(dimension))


def pii_requested(*values: Any, policies: dict[str, Any] | None = None) -> bool:
    text = " ".join(str(value or "") for value in values)
    if _PII_RE.search(text):
        return True
    policy = policies or {}
    for key in ("denied_fields", "masked_fields", "deny_patterns"):
        raw = policy.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                raw_item = " ".join(str(value) for value in item.values())
            else:
                raw_item = str(item)
            if raw_item and raw_item.casefold() in text.casefold():
                return True
    return False


def require_semantic_package(asset: dict[str, Any]) -> dict[str, Any]:
    if asset.get("asset_type") != "semantic_model":
        raise KnowledgeAssetServiceError("AskData 需要选择已发布的 Semantic Skill。")
    package = asset.get("capability_package")
    if not isinstance(package, dict):
        raise KnowledgeAssetServiceError("Semantic Skill 缺少能力包。")
    mdl = package.get("mdl")
    artifacts = (
        package.get("artifacts")
        if isinstance(package.get("artifacts"), dict)
        else package.get("files")
        if isinstance(package.get("files"), dict)
        else {}
    )
    has_artifact_mdl = any(
        isinstance(artifacts.get(path), dict)
        for path in (
            "mdl/models.json",
            "mdl/metrics.json",
            "mdl/dimensions.json",
            "mdl/permissions.json",
            "mdl/freshness.json",
        )
    )
    if not isinstance(mdl, dict) and not has_artifact_mdl:
        raise KnowledgeAssetServiceError("Semantic Skill 缺少 mdl 定义。")
    return package


def redacted(value: Any) -> Any:
    return redact_sensitive(value)
