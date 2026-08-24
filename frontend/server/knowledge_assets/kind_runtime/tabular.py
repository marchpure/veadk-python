"""Small deterministic parsers used by Worker 3 handlers."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any

SENSITIVE_FIELD = re.compile(
    r"(password|passwd|secret|token|api.?key|phone|mobile|email|address|ssn|id.?card|document)",
    re.I,
)


def parse_rows(content: str) -> list[dict[str, Any]]:
    stripped = content.strip()
    if not stripped:
        return []
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            records = []
            for line in stripped.splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
            return [
                {str(key): _coerce(value) for key, value in item.items()}
                for item in records
            ]
        if isinstance(parsed, dict):
            records = parsed.get("rows") or parsed.get("data") or [parsed]
        else:
            records = parsed
        if not isinstance(records, list):
            return []
        return [
            {str(key): _coerce(value) for key, value in item.items()}
            for item in records
            if isinstance(item, dict)
        ]
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return []
    return [{key: _coerce(value) for key, value in row.items()} for row in reader]


def text_chunks(content: str) -> list[str]:
    return [chunk.strip() for chunk in re.split(r"\n\s*\n|\n", content) if chunk.strip()]


def infer_fields(rows: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    if not rows:
        return [], [], []
    keys = list(rows[0].keys())
    numeric: list[str] = []
    date_like: list[str] = []
    dimensions: list[str] = []
    for key in keys:
        values = [row.get(key) for row in rows if row.get(key) not in (None, "")]
        if values and all(isinstance(value, (int, float)) for value in values):
            numeric.append(key)
        elif values and all(_looks_like_date(value) for value in values[:25]):
            date_like.append(key)
        else:
            dimensions.append(key)
    return numeric, dimensions, date_like


def sensitive_fields(rows: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for row in rows:
        keys.update(row)
    return sorted(key for key in keys if SENSITIVE_FIELD.search(key))


def normalize_field(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def duplicate_semantic_names(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    by_normalized: dict[str, list[str]] = {}
    for key in rows[0]:
        by_normalized.setdefault(normalize_field(key), []).append(key)
    return [
        ", ".join(values)
        for values in by_normalized.values()
        if len(set(values)) > 1
    ]


def aggregate_sum(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    metric: str,
    limit: int,
) -> list[tuple[str, float]]:
    grouped: dict[str, float] = {}
    for row in rows:
        label = str(row.get(dimension, "unknown"))
        value = row.get(metric)
        if not isinstance(value, (int, float)):
            continue
        grouped[label] = grouped.get(label, 0.0) + float(value)
    return list(grouped.items())[:limit]


def first_content(request_contents: dict[str, str]) -> tuple[str, str]:
    if not request_contents:
        return "", ""
    key = sorted(request_contents)[0]
    return key, request_contents[key]


def _coerce(value: str | None) -> str | int | float | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "":
        return None
    try:
        integer = int(stripped)
    except ValueError:
        pass
    else:
        return integer
    try:
        return float(stripped)
    except ValueError:
        return stripped


def _looks_like_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            datetime.strptime(value[:19], fmt)
            return True
        except ValueError:
            continue
    return False
