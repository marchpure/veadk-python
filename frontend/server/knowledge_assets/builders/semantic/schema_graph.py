"""Schema graph construction for Semantic Skill generation.

The builder intentionally consumes only schema/profile snapshots. It never
opens source credentials and never samples row-level values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_IDENT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_PII_RE = re.compile(
    r"(customer|cust|buyer|contact|phone|mobile|tel|address|addr|passport|member[_ -]?card|"
    r"vip[_ -]?card|id[_ -]?card|email|mail|person|姓名|客户|电话|手机|地址|护照|会员卡)",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"(date|time|timestamp|created|updated|paid|sell|day|month|year|日期|时间)", re.IGNORECASE)
_ID_RE = re.compile(r"(^id$|_id$|id$|编号|代码)", re.IGNORECASE)
_NUMERIC_RE = re.compile(
    r"(int|integer|bigint|smallint|tinyint|number|numeric|decimal|double|float|real|money|amount|price|qty|quantity|count)",
    re.IGNORECASE,
)
_TEXT_RE = re.compile(r"(char|varchar|text|string|clob|nvarchar|nchar)", re.IGNORECASE)


@dataclass(frozen=True)
class ColumnNode:
    name: str
    data_type: str = "unknown"
    nullable: bool | None = None
    primary_key: bool = False
    foreign_key: dict[str, str] | None = None
    role: str = "field"
    pii: bool = False
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableNode:
    name: str
    schema: str | None = None
    columns: list[ColumnNode] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    row_count: int | None = None
    table_type: str = "dimension"
    business_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RelationshipEdge:
    id: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str = "many-to-one"
    confidence: float = 0.7
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SchemaGraph:
    tables: list[TableNode]
    relationships: list[RelationshipEdge]
    warnings: list[str] = field(default_factory=list)


def build_schema_graph(schema: dict[str, Any], profile: dict[str, Any] | None = None) -> SchemaGraph:
    """Normalize a schema snapshot into tables and relationship edges."""

    tables = _extract_tables(schema, profile or {})
    table_by_name = {_norm(table.name): table for table in tables}
    warnings: list[str] = []
    relationships: list[RelationshipEdge] = []
    seen: set[tuple[str, str, str, str]] = set()

    for table in tables:
        for column in table.columns:
            fk = column.foreign_key or _infer_foreign_key(table, column, table_by_name)
            if not fk:
                continue
            target_table = str(fk.get("table") or fk.get("to_table") or "").strip()
            target_column = str(fk.get("column") or fk.get("to_column") or "id").strip()
            if not target_table:
                continue
            key = (_norm(table.name), _norm(column.name), _norm(target_table), _norm(target_column))
            if key in seen:
                continue
            seen.add(key)
            confidence = 0.9 if column.foreign_key else 0.62
            relationships.append(
                RelationshipEdge(
                    id=_slug(f"{table.name}_to_{target_table}_{column.name}"),
                    from_table=table.name,
                    from_column=column.name,
                    to_table=target_table,
                    to_column=target_column,
                    cardinality="many-to-one",
                    confidence=confidence,
                    evidence=[
                        {
                            "kind": "foreign_key" if column.foreign_key else "name_inference",
                            "table": table.name,
                            "column": column.name,
                            "target_table": target_table,
                            "target_column": target_column,
                            "confidence": confidence,
                        }
                    ],
                )
            )

    classified = [_classify_table(table, relationships) for table in tables]
    if not classified:
        warnings.append("未找到可用于语义构建的表。")
    if classified and not relationships:
        warnings.append("未发现外键或可置信的 join path，跨表维度会被保守禁用。")
    return SchemaGraph(tables=classified, relationships=relationships, warnings=warnings)


def is_time_type(data_type: str, name: str = "") -> bool:
    return bool(_TIME_RE.search(f"{name} {data_type}"))


def is_numeric_type(data_type: str, name: str = "") -> bool:
    return bool(_NUMERIC_RE.search(f"{name} {data_type}")) and not is_time_type(data_type, name)


def is_text_type(data_type: str, name: str = "") -> bool:
    return bool(_TEXT_RE.search(f"{name} {data_type}"))


def is_identifier_name(name: str) -> bool:
    return bool(_ID_RE.search(name))


def is_pii_name(name: str) -> bool:
    return bool(_PII_RE.search(name))


def slugify(value: str, *, fallback: str = "item") -> str:
    return _slug(value, fallback=fallback)


def _extract_tables(schema: dict[str, Any], profile: dict[str, Any]) -> list[TableNode]:
    raw_tables: list[dict[str, Any]] = []
    if isinstance(schema.get("tables"), list):
        raw_tables.extend(_dict_items(schema["tables"]))
    if isinstance(schema.get("schemas"), list):
        for namespace in _dict_items(schema["schemas"]):
            namespace_name = str(namespace.get("name") or namespace.get("schema") or "").strip() or None
            for table in _dict_items(namespace.get("tables")):
                raw_tables.append({**table, "schema": table.get("schema") or namespace_name})
    if isinstance(schema.get("database"), dict):
        raw_tables.extend(_dict_items(schema["database"].get("tables")))
    if not raw_tables and isinstance(schema.get("fields"), list):
        raw_tables.append({"name": schema.get("name") or "source", "columns": schema.get("fields")})

    out: list[TableNode] = []
    for raw in raw_tables:
        name = str(raw.get("name") or raw.get("table") or raw.get("table_name") or "").strip()
        if not name:
            continue
        table_profile = _profile_for_table(profile, name)
        columns = _extract_columns(raw, table_profile)
        if not columns:
            continue
        raw_pk = raw.get("primary_key") or raw.get("primaryKey") or raw.get("primary_keys") or []
        primary_key = _string_list(raw_pk)
        if not primary_key:
            primary_key = [column.name for column in columns if column.primary_key]
        if not primary_key:
            primary_key = [
                column.name
                for column in columns
                if _norm(column.name) in {"id", f"{_norm(name)}_id", f"{_norm(name)}id"}
            ][:1]
        columns = [
            ColumnNode(
                name=column.name,
                data_type=column.data_type,
                nullable=column.nullable,
                primary_key=column.primary_key or column.name in primary_key,
                foreign_key=column.foreign_key,
                role=_column_role(column.name, column.data_type, column.name in primary_key, column.pii),
                pii=column.pii,
                profile=column.profile,
            )
            for column in columns
        ]
        out.append(
            TableNode(
                name=name,
                schema=str(raw.get("schema") or raw.get("namespace") or "").strip() or None,
                columns=columns,
                primary_key=primary_key,
                row_count=_int_or_none(raw.get("row_count") or raw.get("rowCount") or table_profile.get("row_count")),
            )
        )
    return out


def _extract_columns(raw_table: dict[str, Any], table_profile: dict[str, Any]) -> list[ColumnNode]:
    raw_columns = (
        raw_table.get("columns")
        or raw_table.get("fields")
        or raw_table.get("properties")
        or []
    )
    out: list[ColumnNode] = []
    for raw in _dict_items(raw_columns):
        name = str(raw.get("name") or raw.get("column") or raw.get("field") or raw.get("source_field") or "").strip()
        if not name:
            continue
        data_type = str(raw.get("type") or raw.get("data_type") or raw.get("dataType") or "unknown").strip() or "unknown"
        column_profile = _profile_for_column(table_profile, name)
        fk = raw.get("foreign_key") or raw.get("foreignKey") or raw.get("references")
        out.append(
            ColumnNode(
                name=name,
                data_type=data_type,
                nullable=_bool_or_none(raw.get("nullable")),
                primary_key=bool(raw.get("primary_key") or raw.get("primaryKey") or raw.get("is_primary_key")),
                foreign_key=fk if isinstance(fk, dict) else None,
                role="field",
                pii=bool(raw.get("pii") or raw.get("sensitive") or is_pii_name(name)),
                profile=column_profile,
            )
        )
    return out


def _classify_table(table: TableNode, relationships: list[RelationshipEdge]) -> TableNode:
    outgoing = [rel for rel in relationships if _norm(rel.from_table) == _norm(table.name)]
    incoming = [rel for rel in relationships if _norm(rel.to_table) == _norm(table.name)]
    business_fields = [
        column.name
        for column in table.columns
        if not column.primary_key
        and not column.foreign_key
        and not is_identifier_name(column.name)
        and not column.pii
    ]
    numeric_count = sum(1 for column in table.columns if is_numeric_type(column.data_type, column.name) and not column.primary_key)
    time_count = sum(1 for column in table.columns if is_time_type(column.data_type, column.name))
    table_name = table.name.lower()
    table_type = "dimension"
    if len(outgoing) >= 2 and len(business_fields) <= 1:
        table_type = "bridge"
    if numeric_count >= 1 or time_count >= 1 or any(term in table_name for term in ("order", "sale", "fact", "transaction", "ticket", "event")):
        table_type = "fact"
    if outgoing and incoming and len(business_fields) > 1:
        table_type = "association"
    return TableNode(
        name=table.name,
        schema=table.schema,
        columns=table.columns,
        primary_key=table.primary_key,
        row_count=table.row_count,
        table_type=table_type,
        business_fields=business_fields,
    )


def _column_role(name: str, data_type: str, primary_key: bool, pii: bool) -> str:
    if primary_key:
        return "primary_key"
    if pii:
        return "masked"
    if is_time_type(data_type, name):
        return "time"
    if is_numeric_type(data_type, name) and not is_identifier_name(name):
        return "measure"
    if is_text_type(data_type, name):
        return "dimension"
    return "field"


def _infer_foreign_key(table: TableNode, column: ColumnNode, tables: dict[str, TableNode]) -> dict[str, str] | None:
    if column.primary_key:
        return None
    normalized = _norm(column.name)
    if not normalized.endswith("id") and not normalized.endswith("_id"):
        return None
    base = normalized.removesuffix("_id").removesuffix("id")
    if not base or base == _norm(table.name):
        return None
    candidates = [base, f"{base}s", base.removesuffix("s")]
    for candidate in candidates:
        target = tables.get(candidate)
        if not target:
            continue
        target_column = target.primary_key[0] if target.primary_key else "id"
        return {"table": target.name, "column": target_column}
    return None


def _profile_for_table(profile: dict[str, Any], table_name: str) -> dict[str, Any]:
    for container_key in ("tables", "profiles"):
        value = profile.get(container_key)
        if isinstance(value, dict):
            for key, item in value.items():
                if _norm(key) == _norm(table_name) and isinstance(item, dict):
                    return item
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and _norm(str(item.get("name") or item.get("table") or "")) == _norm(table_name):
                    return item
    if _norm(str(profile.get("table") or profile.get("name") or "")) == _norm(table_name):
        return profile
    return {}


def _profile_for_column(table_profile: dict[str, Any], column_name: str) -> dict[str, Any]:
    value = table_profile.get("columns") or table_profile.get("fields") or {}
    if isinstance(value, dict):
        for key, item in value.items():
            if _norm(key) == _norm(column_name) and isinstance(item, dict):
                return item
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and _norm(str(item.get("name") or item.get("column") or "")) == _norm(column_name):
                return item
    return {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [{**item, "name": key} if isinstance(item, dict) and "name" not in item else item for key, item in value.items() if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y"}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str, *, fallback: str = "item") -> str:
    text = _IDENT_RE.sub("_", value.strip().lower()).strip("_")
    text = re.sub(r"_+", "_", text)
    return text[:96] or fallback


def _norm(value: str) -> str:
    return _slug(value, fallback="")
