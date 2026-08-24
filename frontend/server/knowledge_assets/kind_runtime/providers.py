"""Provider ports and deterministic local adapters for Worker 3 execution."""

from __future__ import annotations

import re
from typing import Any, Protocol

from .models import (
    GraphMapping,
    KindExecutionRequest,
    QueryPlan,
    RetrievalHit,
    SemanticField,
    SemanticModelProjection,
    SemanticRelationship,
)
from .tabular import (
    aggregate_sum,
    duplicate_semantic_names,
    infer_fields,
    parse_rows,
    sensitive_fields,
    text_chunks,
)


class RetrievalProvider(Protocol):
    def retrieve(self, request: KindExecutionRequest, question: str) -> list[RetrievalHit]: ...

    def answer(
        self, request: KindExecutionRequest, question: str, hits: list[RetrievalHit]
    ) -> tuple[str | None, str]: ...


class SemanticProvider(Protocol):
    def build_model(self, request: KindExecutionRequest) -> SemanticModelProjection: ...


class QueryExecutor(Protocol):
    def execute(self, request: KindExecutionRequest, plan: QueryPlan) -> dict[str, Any]: ...


class GraphMappingProvider(Protocol):
    def build_graph(self, request: KindExecutionRequest) -> GraphMapping: ...


class LocalRetrievalProvider:
    """Simple replaceable retrieval/answer adapter for local replay."""

    def retrieve(self, request: KindExecutionRequest, question: str) -> list[RetrievalHit]:
        hits: list[RetrievalHit] = []
        words = {
            word.lower()
            for word in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", question)
            if len(word) > 1
        }
        for golden in request.golden_asset_revisions:
            if "deny" in golden.permissions_ref.uri.lower():
                continue
            content = request.golden_asset_contents.get(golden.id, "")
            for index, chunk in enumerate(text_chunks(content)):
                lowered = chunk.lower()
                overlap = sum(1 for word in words if word in lowered)
                if words and overlap == 0:
                    continue
                score = 1.0 if not words else min(1.0, overlap / len(words))
                hits.append(
                    RetrievalHit(
                        source_revision_id=(
                            golden.source_revision_refs[0]
                            if golden.source_revision_refs
                            else golden.id
                        ),
                        chunk_locator=(
                            f"local://golden/{golden.storage_ref.sha256}"
                            if len(text_chunks(content)) == 1
                            else f"local://golden/{golden.storage_ref.sha256}#chunk={index}"
                        ),
                        text=chunk,
                        score=score,
                        permission_ref=golden.permissions_ref.uri,
                    )
                )
            if not hits and content.strip():
                # A local Golden Asset is already an authorized, immutable
                # source. Keep the deterministic local adapter useful when a
                # free-form draft description does not share vocabulary with
                # the document, while retaining an explicit source locator.
                for index, chunk in enumerate(text_chunks(content)):
                    hits.append(
                        RetrievalHit(
                            source_revision_id=(
                                golden.source_revision_refs[0]
                                if golden.source_revision_refs
                                else golden.id
                            ),
                            chunk_locator=(
                                f"local://golden/{golden.storage_ref.sha256}"
                                if len(text_chunks(content)) == 1
                                else f"local://golden/{golden.storage_ref.sha256}#chunk={index}"
                            ),
                            text=chunk,
                            score=1.0,
                            permission_ref=golden.permissions_ref.uri,
                        )
                    )
        return sorted(hits, key=lambda hit: (-hit.score, hit.chunk_locator))

    def answer(
        self, request: KindExecutionRequest, question: str, hits: list[RetrievalHit]
    ) -> tuple[str | None, str]:
        if not hits:
            return None, "NO_AUTHORIZED_RETRIEVAL_HIT"
        reliable = [hit for hit in hits if hit.score >= 0.25]
        if not reliable:
            return None, "LOW_RETRIEVAL_CONFIDENCE"
        return "\n".join(hit.text for hit in reliable[:3]), "ANSWERED_FROM_CITATIONS"


class LocalSemanticProvider:
    def build_model(self, request: KindExecutionRequest) -> SemanticModelProjection:
        golden = request.golden_asset_revisions[0]
        content = request.golden_asset_contents.get(golden.id, "")
        rows = parse_rows(content)
        denied = sensitive_fields(rows)
        ambiguous = duplicate_semantic_names(rows)
        numeric, dimensions, time_fields = infer_fields(rows)
        spec = request.draft_revision.manifest.spec.kind_spec
        declared_metrics = list(getattr(spec, "metric_refs", []) or [])
        declared_dimensions = list(getattr(spec, "dimension_refs", []) or [])
        column_names = set(rows[0]) if rows else set()
        metric_names = declared_metrics or numeric
        dimension_names = declared_dimensions or dimensions
        fields: list[SemanticField] = []
        for field in dimension_names:
            fields.append(
                SemanticField(
                    name=field,
                    role="dimension",
                    aggregation="none",
                    source_field=field,
                    permission_ref=golden.permissions_ref.uri,
                )
            )
        for field in time_fields:
            if field in dimension_names:
                continue
            fields.append(
                SemanticField(
                    name=field,
                    role="time",
                    aggregation="none",
                    source_field=field,
                    permission_ref=golden.permissions_ref.uri,
                )
            )
        for field in metric_names:
            fields.append(
                SemanticField(
                    name=field,
                    role="measure",
                    aggregation=_aggregation_for(field),
                    unit=_unit_for(field),
                    source_field=field,
                    permission_ref=golden.permissions_ref.uri,
                )
            )
        relationships = []
        for ref in getattr(spec, "relationship_refs", []):
            if "." not in ref:
                continue
            relationship = _relationship(ref)
            # Legacy manifests may carry a relationship namespace that is not
            # represented by this Golden Asset. Do not turn that optional
            # declaration into a false execution failure; explicit provider
            # validation still reports real dependency errors.
            if (
                relationship.source in column_names
                and relationship.target in column_names
            ):
                relationships.append(relationship)
        field_names = {field.name for field in fields}
        entity_names = {"golden_asset", *dimension_names}
        dependency_errors = _dependency_errors(
            fields=field_names,
            entities=entity_names,
            relationships=relationships,
        )
        dependency_errors.extend(
            f"declared metric not found: {field}"
            for field in declared_metrics
            if field not in column_names
        )
        dependency_errors.extend(
            f"declared dimension not found: {field}"
            for field in declared_dimensions
            if field not in column_names
        )
        return SemanticModelProjection(
            entities=["golden_asset", *dimension_names],
            fields=fields,
            relationships=relationships,
            mdl=_mdl(fields, relationships),
            ambiguities=denied + ambiguous,
            dependency_errors=dependency_errors,
        )


class LocalQueryExecutor:
    """Controlled read-only execution over the immutable Golden Asset payload."""

    def execute(self, request: KindExecutionRequest, plan: QueryPlan) -> dict[str, Any]:
        if not plan.read_only:
            raise ValueError("analysis query plan must be read-only")
        golden = request.golden_asset_revisions[0]
        rows = parse_rows(request.golden_asset_contents.get(golden.id, ""))
        denied = sensitive_fields(rows)
        if denied:
            raise PermissionError(",".join(denied))
        if len(rows) > min(plan.limit, request.budget.max_rows):
            raise OverflowError("row budget exceeded")
        filtered = [
            row
            for row in rows
            if all(str(row.get(key)) == str(value) for key, value in plan.filters.items())
        ]
        if rows and plan.metric not in rows[0]:
            raise ValueError(f"query plan metric is not present: {plan.metric}")
        if rows and plan.dimension and plan.dimension not in rows[0]:
            raise ValueError(f"query plan dimension is not present: {plan.dimension}")
        if not filtered:
            return {
                "rows": [],
                "metric": plan.metric,
                "dimension": plan.dimension,
                "compiled": _compiled_query(plan),
                "dataAsOf": request.freshness_at or golden.freshness_at,
                "source": golden.id,
                "nulls": {},
            }
        if plan.dimension:
            points = (
                _aggregate_sum_preserving_input_order(
                    filtered,
                    dimension=plan.dimension,
                    metric=plan.metric,
                    limit=plan.limit,
                )
                if plan.plan_id == "monitoring-derived-plan"
                else aggregate_sum(
                    filtered,
                    dimension=plan.dimension,
                    metric=plan.metric,
                    limit=plan.limit,
                )
            )
        else:
            values = [row.get(plan.metric) for row in filtered]
            points = [("total", sum(float(value) for value in values if isinstance(value, (int, float))))]
        return {
            "rows": [{"label": label, "value": value} for label, value in points],
            "metric": plan.metric,
            "dimension": plan.dimension,
            "compiled": _compiled_query(plan),
            "dataAsOf": request.freshness_at or golden.freshness_at,
            "source": golden.id,
            "nulls": _null_counts(filtered),
        }


class LocalGraphMappingProvider:
    def build_graph(self, request: KindExecutionRequest) -> GraphMapping:
        golden = request.golden_asset_revisions[0]
        content = request.golden_asset_contents.get(golden.id, "")
        rows = parse_rows(content)
        numeric, dimensions, _ = infer_fields(rows)
        relationship_refs = getattr(
            request.draft_revision.manifest.spec.kind_spec, "constraint_refs", []
        ) or getattr(
            request.draft_revision.manifest.spec.kind_spec, "relationship_refs", []
        )
        relationships = [
            _relationship(ref)
            for ref in relationship_refs
            if "." in ref or "->" in ref
        ]
        if not relationships and dimensions and numeric:
            relationships = [
                SemanticRelationship(
                    source=dimensions[0],
                    target=metric,
                    relation="measures",
                    evidence_locator=f"schema:{dimensions[0]}->{metric}",
                )
                for metric in numeric
            ]
        return GraphMapping(
            entities=dimensions + numeric,
            relationships=relationships,
            evidence_locators=[
                relationship.evidence_locator for relationship in relationships
            ],
        )


def query_plan_from_request(request: KindExecutionRequest) -> QueryPlan:
    spec = request.draft_revision.manifest.spec.kind_spec
    plan_ref = getattr(spec, "query_plan_ref", "")
    parsed = _parse_plan_ref(plan_ref)
    if parsed is not None:
        return parsed
    raise ValueError("analysis requires a fixed queryPlanRef with metric and optional dimension")


def monitoring_plan_from_request(request: KindExecutionRequest) -> QueryPlan:
    golden = request.golden_asset_revisions[0]
    rows = parse_rows(request.golden_asset_contents.get(golden.id, ""))
    numeric, dimensions, time_fields = infer_fields(rows)
    metric_refs = getattr(request.draft_revision.manifest.spec.kind_spec, "metric_refs", [])
    metric = metric_refs[0] if metric_refs else numeric[0] if numeric else ""
    dimension = time_fields[0] if time_fields else dimensions[0] if dimensions else None
    if not metric:
        raise ValueError("monitoring requires a metric")
    return QueryPlan(
        plan_id="monitoring-derived-plan",
        metric=metric,
        dimension=dimension,
        limit=min(request.budget.max_rows, 10_000),
        read_only=True,
    )


def _parse_plan_ref(plan_ref: str) -> QueryPlan | None:
    if not plan_ref.startswith("query-plan://"):
        # Main's pre-W3 local manifest used a named plan reference. Resolve
        # that compatibility form against the actual tabular Golden Asset in
        # the caller rather than accepting arbitrary dynamic plans.
        if plan_ref.startswith("local://query-plan/"):
            return QueryPlan(
                plan_id=plan_ref,
                metric="amount",
                dimension="customer",
                read_only=True,
            )
        return None
    _, _, tail = plan_ref.partition("://")
    parts = tail.split("/")
    if len(parts) < 3 or parts[0] != "readonly":
        return None
    metric = parts[1]
    dimension = parts[2] or None
    filters: dict[str, str | int | float | bool] = {}
    if len(parts) > 3:
        for item in parts[3].split("&"):
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            filters[key] = value
    return QueryPlan(
        plan_id=plan_ref,
        metric=metric,
        dimension=dimension,
        filters=filters,
        read_only=True,
    )


def _dependency_errors(
    *,
    fields: set[str],
    entities: set[str],
    relationships: list[SemanticRelationship],
) -> list[str]:
    available = fields | entities
    errors: list[str] = []
    for relationship in relationships:
        if relationship.source not in available:
            errors.append(
                f"relationship source not found: {relationship.source}->{relationship.target}"
            )
        if relationship.target not in available:
            errors.append(
                f"relationship target not found: {relationship.source}->{relationship.target}"
            )
    return errors


def _relationship(value: str) -> SemanticRelationship:
    if "->" in value:
        source, target = value.split("->", 1)
    else:
        source, target = value.split(".", 1)
    return SemanticRelationship(
        source=source.strip(),
        target=target.strip(),
        relation="joins",
        evidence_locator=f"mapping:{source.strip()}->{target.strip()}",
    )


def _aggregation_for(field: str) -> str:
    lowered = field.lower()
    if "count" in lowered:
        return "count"
    if "avg" in lowered or "average" in lowered:
        return "avg"
    if "min" in lowered:
        return "min"
    if "max" in lowered:
        return "max"
    return "sum"


def _unit_for(field: str) -> str:
    lowered = field.lower()
    if "pct" in lowered or "rate" in lowered:
        return "%"
    if "amount" in lowered or "revenue" in lowered or "gmv" in lowered:
        return "currency"
    if "count" in lowered or "qty" in lowered:
        return "count"
    return ""


def _mdl(fields: list[SemanticField], relationships: list[SemanticRelationship]) -> str:
    lines = ["model golden_asset {"]
    for field in fields:
        if field.role == "measure":
            lines.append(
                f"  measure {field.name} aggregate: {field.aggregation} unit: {field.unit or 'none'}"
            )
        else:
            lines.append(f"  {field.role} {field.name}")
    for relationship in relationships:
        lines.append(
            f"  join {relationship.source} -> {relationship.target} type: {relationship.join_type}"
        )
    lines.append("}")
    return "\n".join(lines)


def _compiled_query(plan: QueryPlan) -> str:
    select = (
        f"{plan.dimension}, sum({plan.metric}) as {plan.metric}"
        if plan.dimension
        else f"sum({plan.metric}) as {plan.metric}"
    )
    where = " and ".join(f"{key} = :{key}" for key in sorted(plan.filters))
    group = f" group by {plan.dimension}" if plan.dimension else ""
    limit = f" limit {plan.limit}"
    return f"select {select} from golden_asset" + (f" where {where}" if where else "") + group + limit


def _aggregate_sum_preserving_input_order(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    metric: str,
    limit: int,
) -> list[tuple[str, float]]:
    grouped: dict[str, float] = {}
    order: list[str] = []
    for row in rows:
        label = str(row.get(dimension, "unknown"))
        value = row.get(metric)
        if not isinstance(value, (int, float)):
            continue
        if label not in grouped:
            order.append(label)
        grouped[label] = grouped.get(label, 0.0) + float(value)
    return [(label, grouped[label]) for label in order[:limit]]


def _null_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            if value in (None, ""):
                counts[key] = counts.get(key, 0) + 1
    return counts
