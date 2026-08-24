"""Five explicit Worker 3 Skill kind handlers."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from frontend.server.knowledge_assets.contracts import (
    ChartSeries,
    ChartViewModel,
    GraphEdge,
    GraphNode,
    GraphOntologyViewModel,
    KnowledgeCitation,
    KnowledgeViewModel,
    MonitoringViewModel,
    SemanticViewModel,
)

from .models import ExecutionEvidence, KindExecutionRequest, KindHandlerOutput
from .tabular import (
    aggregate_sum,
    duplicate_semantic_names,
    first_content,
    infer_fields,
    parse_rows,
    sensitive_fields,
    text_chunks,
)


class KindHandler:
    kind: str

    def execute(self, request: KindExecutionRequest) -> KindHandlerOutput:
        raise NotImplementedError


class KnowledgeHandler(KindHandler):
    kind = "knowledge"

    def execute(self, request: KindExecutionRequest) -> KindHandlerOutput:
        golden, content = _first_golden(request)
        if golden is None or not content.strip():
            return KindHandlerOutput(
                state="no_data",
                template="knowledge",
                purpose="answer",
                message="Knowledge execution requires a non-empty Golden Asset.",
            )
        if _denied(golden.permissions_ref.uri):
            return KindHandlerOutput(
                state="permission_denied",
                template="knowledge",
                purpose="answer",
                view_model=KnowledgeViewModel(
                    answer="权限策略拒绝访问该知识来源。",
                    refusal=True,
                ),
                message="Golden Asset permission policy denied retrieval.",
            )
        chunks = text_chunks(content)
        query = request.draft_revision.manifest.metadata.description
        words = {word.lower() for word in re.findall(r"[\w\u4e00-\u9fff]+", query)}
        matched = [
            chunk for chunk in chunks
            if not words or any(word in chunk.lower() for word in words)
        ][:3]
        state = "ok" if matched else "unable_to_answer"
        answer = "\n".join(matched) if matched else "无法根据已授权知识来源回答。"
        evidence = [
            _evidence(
                request,
                source_revision_id,
                golden.id,
                f"local://golden/{golden.storage_ref.sha256}#chunk={index}",
            )
            for index, source_revision_id in enumerate(golden.source_revision_refs or [golden.id])
        ][: max(1, len(matched))]
        return KindHandlerOutput(
            state=state,
            template="knowledge",
            purpose="answer",
            view_model=KnowledgeViewModel(
                answer=answer,
                refusal=state == "unable_to_answer",
                citations=[
                    KnowledgeCitation(
                        citation_id=item.evidence_id,
                        source_revision_id=item.source_revision_id,
                        title="Golden Asset Revision",
                        locator=item.locator,
                        excerpt_ref=item.evidence_ref,
                    )
                    for item in evidence
                ],
            ),
            payload={
                "answer": answer,
                "state": state,
                "citations": [item.model_dump(mode="json", by_alias=True) for item in evidence],
            },
            evidence=evidence,
        )


class SemanticHandler(KindHandler):
    kind = "semantic"

    def execute(self, request: KindExecutionRequest) -> KindHandlerOutput:
        golden, content = _first_golden(request)
        rows = parse_rows(content)
        if golden is None or not rows:
            return KindHandlerOutput(
                state="no_data",
                template="semantic",
                purpose="schema",
                message="Semantic execution requires structured rows.",
            )
        denied_fields = sensitive_fields(rows)
        if denied_fields:
            return KindHandlerOutput(
                state="permission_denied",
                template="semantic",
                purpose="schema",
                payload={"deniedFields": denied_fields},
                message="Field-level permission policy rejected sensitive columns.",
            )
        ambiguous = duplicate_semantic_names(rows)
        if ambiguous:
            return KindHandlerOutput(
                state="schema_drift",
                template="semantic",
                purpose="schema",
                payload={"ambiguousFields": ambiguous},
                message="Ambiguous field names require semantic review.",
            )
        numeric, dimensions, date_like = infer_fields(rows)
        spec = request.draft_revision.manifest.spec.kind_spec
        cycle = _relationship_cycle(getattr(spec, "relationship_refs", []))
        if cycle:
            return KindHandlerOutput(
                state="validation_failed",
                template="semantic",
                purpose="schema",
                payload={"cycle": cycle},
                message="Semantic relationship cycle detected.",
            )
        metric_refs = list(getattr(spec, "metric_refs", []) or numeric)
        dimension_refs = list(getattr(spec, "dimension_refs", []) or dimensions + date_like)
        relationship_refs = list(getattr(spec, "relationship_refs", []))
        return KindHandlerOutput(
            state="ok",
            template="semantic",
            purpose="schema",
            view_model=SemanticViewModel(
                schema_ref=golden.schema_ref,
                metric_refs=metric_refs,
                dimension_refs=dimension_refs,
                relationship_refs=relationship_refs,
                data_ref=golden.storage_ref,
            ),
            payload={
                "entities": [{"name": "golden_asset", "source": golden.id}],
                "metrics": [
                    {"name": name, "aggregation": "sum", "unit": _unit_for(name)}
                    for name in metric_refs
                ],
                "dimensions": [{"name": name} for name in dimension_refs],
                "timeSemantics": [{"field": name, "grain": "day"} for name in date_like],
                "relationships": relationship_refs,
                "permissions": {"policyRef": request.draft_revision.manifest.spec.policy_ref.uri},
                "editableMdl": _mdl(metric_refs, dimension_refs, relationship_refs),
            },
            evidence=[_evidence(request, golden.source_revision_refs[0] if golden.source_revision_refs else golden.id, golden.id, "schema:0")],
        )


class AnalysisHandler(KindHandler):
    kind = "analysis"

    def execute(self, request: KindExecutionRequest) -> KindHandlerOutput:
        golden, content = _first_golden(request)
        rows = parse_rows(content)
        if golden is None or not rows:
            return KindHandlerOutput(
                state="no_data",
                template="chart",
                purpose="compare",
                message="Analysis execution requires structured rows.",
            )
        denied_fields = sensitive_fields(rows)
        if denied_fields:
            return KindHandlerOutput(
                state="permission_denied",
                template="chart",
                purpose="compare",
                payload={"deniedFields": denied_fields},
                message="Field-level permission policy rejected sensitive columns.",
            )
        numeric, dimensions, date_like = infer_fields(rows)
        if not numeric:
            return KindHandlerOutput(
                state="awaiting_input",
                template="chart",
                purpose="compare",
                message="Analysis requires at least one numeric measure.",
            )
        dimension = dimensions[0] if dimensions else date_like[0] if date_like else "_row"
        metric = numeric[0]
        if len(rows) > request.budget.max_rows:
            return KindHandlerOutput(
                state="over_budget",
                template="chart",
                purpose="compare",
                payload={"rowCount": len(rows), "maxRows": request.budget.max_rows},
                message="Analysis row budget exceeded.",
            )
        points = (
            aggregate_sum(rows, dimension=dimension, metric=metric, limit=request.budget.max_rows)
            if dimension != "_row"
            else [(str(index + 1), float(row[metric])) for index, row in enumerate(rows)]
        )
        if not points:
            return KindHandlerOutput(
                state="no_data",
                template="chart",
                purpose="compare",
                message="No numeric values remained after filtering nulls.",
            )
        values = [value for _, value in points]
        return KindHandlerOutput(
            state="ok",
            template="chart",
            purpose="compare",
            view_model=ChartViewModel(
                title=request.draft_revision.manifest.metadata.display_name,
                x_field=dimension,
                y_field=metric,
                series=[ChartSeries(name=metric, points=points)],
                data_ref=golden.storage_ref,
            ),
            payload={
                "query": {
                    "kind": "parameterized_aggregate",
                    "measure": metric,
                    "dimension": None if dimension == "_row" else dimension,
                    "limit": request.budget.max_rows,
                    "readonly": True,
                },
                "kpis": [
                    {"key": f"sum_{metric}", "value": sum(values), "unit": _unit_for(metric)},
                    {"key": "row_count", "value": len(rows), "unit": "rows"},
                ],
                "trends": [{"label": label, "value": value} for label, value in points],
                "nulls": _null_counts(rows),
                "dataAsOf": request.freshness_at or golden.freshness_at,
                "source": golden.id,
            },
            evidence=[_evidence(request, golden.source_revision_refs[0] if golden.source_revision_refs else golden.id, golden.id, f"query:{metric}")],
        )


class GraphOntologyHandler(KindHandler):
    kind = "graph_ontology"

    def execute(self, request: KindExecutionRequest) -> KindHandlerOutput:
        golden, content = _first_golden(request)
        rows = parse_rows(content)
        chunks = text_chunks(content)
        if golden is None or (not rows and not chunks):
            return KindHandlerOutput(
                state="no_data",
                template="graph_ontology",
                purpose="explore",
                message="Graph ontology execution requires schema rows or document chunks.",
            )
        numeric, dimensions, _ = infer_fields(rows)
        node_names = dimensions + numeric if rows else [chunk[:48] for chunk in chunks]
        page_size = min(request.budget.max_rows, 500)
        nodes = [
            GraphNode(
                id=f"node-{index}",
                label=name,
                entity_type="metric" if name in numeric else "entity",
            )
            for index, name in enumerate(node_names[:page_size])
        ]
        edges = [
            GraphEdge(source=nodes[index - 1].id, target=node.id, relation="related_to")
            for index, node in enumerate(nodes)
            if index
        ]
        conflicts = duplicate_semantic_names(rows)
        return KindHandlerOutput(
            state="schema_drift" if conflicts else "ok",
            template="graph_ontology",
            purpose="explore",
            view_model=GraphOntologyViewModel(
                nodes=nodes,
                edges=edges,
                evidence_ref=golden.storage_ref,
            ),
            payload={
                "ontology": {"entities": [node.model_dump(mode="json", by_alias=True) for node in nodes]},
                "relations": [edge.model_dump(mode="json", by_alias=True) for edge in edges],
                "pagination": {"offset": 0, "limit": page_size, "total": len(node_names)},
                "conflicts": conflicts,
                "versionCompare": {
                    "base": request.draft_revision.golden_asset_revision_refs,
                    "current": [golden.id],
                },
            },
            evidence=[_evidence(request, golden.source_revision_refs[0] if golden.source_revision_refs else golden.id, golden.id, "ontology:0")],
        )


class MonitoringHandler(KindHandler):
    kind = "monitoring"

    def execute(self, request: KindExecutionRequest) -> KindHandlerOutput:
        golden, content = _first_golden(request)
        rows = parse_rows(content)
        if golden is None or not rows:
            return KindHandlerOutput(
                state="no_data",
                template="monitoring",
                purpose="monitor",
                message="Monitoring requires prior analysis rows.",
            )
        numeric, dimensions, date_like = infer_fields(rows)
        if not numeric:
            return KindHandlerOutput(
                state="awaiting_input",
                template="monitoring",
                purpose="monitor",
                message="Monitoring requires at least one metric.",
            )
        metric = numeric[0]
        dimension = date_like[0] if date_like else dimensions[0] if dimensions else "_row"
        if dimension == "_row":
            values = [(str(index + 1), float(row[metric])) for index, row in enumerate(rows)]
        elif date_like and dimension == date_like[0]:
            values = [
                (str(row.get(dimension, index + 1)), float(row[metric]))
                for index, row in enumerate(rows[: request.budget.max_rows])
                if isinstance(row.get(metric), (int, float))
            ]
        else:
            values = aggregate_sum(
                rows, dimension=dimension, metric=metric, limit=request.budget.max_rows
            )
        threshold = _threshold(getattr(request.draft_revision.manifest.spec.kind_spec, "alert_policy_ref", ""))
        latest = values[-1][1] if values else 0.0
        previous = values[-2][1] if len(values) > 1 else latest
        change_rate = 0.0 if previous == 0 else (latest - previous) / abs(previous)
        stale = _stale(golden.freshness_at, request.now, request.budget.freshness_seconds)
        alerts = []
        observations = []
        if threshold is not None and latest >= threshold:
            alerts.append(f"{metric} reached {latest:g}, threshold {threshold:g}")
        if abs(change_rate) >= 0.2 and len(values) > 1:
            alerts.append(f"{metric} changed {change_rate:.0%} since previous point")
        if stale:
            alerts.append("source freshness is stale")
        observations.append(
            {
                "metric": metric,
                "latest": latest,
                "previous": previous,
                "changeRate": change_rate,
                "freshness": golden.freshness_at,
                "lastGood": golden.last_good,
            }
        )
        action_candidates = [
            {
                "type": "review",
                "title": "Review monitoring alert",
                "previewOnly": True,
                "evidenceLocator": "monitoring:latest",
            }
            for _ in alerts[:1]
        ]
        return KindHandlerOutput(
            state="ok",
            template="monitoring",
            purpose="monitor",
            view_model=MonitoringViewModel(
                metric_refs=list(getattr(request.draft_revision.manifest.spec.kind_spec, "metric_refs", []) or [metric]),
                values=values,
                alerts=alerts,
                data_ref=golden.storage_ref,
            ),
            payload={
                "observations": observations,
                "alerts": alerts,
                "actionCandidates": action_candidates,
                "reviewLoop": ["data", "action_candidate", "retrospective", "decision", "evidence"],
                "externalActionsExecuted": False,
            },
            evidence=[_evidence(request, golden.source_revision_refs[0] if golden.source_revision_refs else golden.id, golden.id, "monitoring:latest")],
        )


HANDLERS: dict[str, KindHandler] = {
    handler.kind: handler
    for handler in (
        KnowledgeHandler(),
        SemanticHandler(),
        AnalysisHandler(),
        GraphOntologyHandler(),
        MonitoringHandler(),
    )
}


def _first_golden(request: KindExecutionRequest):
    asset_id, content = first_content(request.golden_asset_contents)
    golden = next(
        (revision for revision in request.golden_asset_revisions if revision.id == asset_id),
        request.golden_asset_revisions[0] if request.golden_asset_revisions else None,
    )
    return golden, content


def _evidence(
    request: KindExecutionRequest,
    source_revision_id: str,
    golden_asset_revision_id: str,
    locator: str,
) -> ExecutionEvidence:
    golden = next(
        item for item in request.golden_asset_revisions if item.id == golden_asset_revision_id
    )
    digest = __import__("hashlib").sha256(
        f"{request.trace_id}:{source_revision_id}:{golden_asset_revision_id}:{locator}".encode()
    ).hexdigest()[:24]
    return ExecutionEvidence(
        evidence_id=f"evidence-{digest}",
        source_revision_id=source_revision_id,
        golden_asset_revision_id=golden_asset_revision_id,
        locator=locator,
        permission_ref=golden.permissions_ref.uri,
    )


def _denied(permission_ref: str) -> bool:
    return "deny" in permission_ref.lower() or "forbidden" in permission_ref.lower()


def _relationship_cycle(relationship_refs: list[str]) -> str | None:
    pairs: set[tuple[str, str]] = set()
    for relation in relationship_refs:
        if "." not in relation:
            continue
        left, right = relation.split(".", 1)
        pair = (left.strip(), right.strip())
        reverse = (pair[1], pair[0])
        if reverse in pairs:
            return f"{pair[0]}.{pair[1]}"
        pairs.add(pair)
    return None


def _unit_for(field: str) -> str:
    lowered = field.lower()
    if "pct" in lowered or "rate" in lowered:
        return "%"
    if "amount" in lowered or "revenue" in lowered or "gmv" in lowered:
        return "currency"
    if "count" in lowered or "qty" in lowered:
        return "count"
    return ""


def _mdl(metrics: list[str], dimensions: list[str], relationships: list[str]) -> str:
    lines = ["model golden_asset {"]
    for dimension in dimensions:
        lines.append(f"  dimension {dimension}")
    for metric in metrics:
        lines.append(f"  measure {metric} aggregate: sum")
    for relationship in relationships:
        lines.append(f"  relationship {relationship}")
    lines.append("}")
    return "\n".join(lines)


def _null_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            if value in (None, ""):
                counts[key] = counts.get(key, 0) + 1
    return counts


def _threshold(policy_ref: str) -> float | None:
    match = re.search(r"threshold[:=/]([0-9]+(?:\.[0-9]+)?)", policy_ref)
    if not match:
        return None
    return float(match.group(1))


def _stale(freshness_at: str, now: str, max_age_seconds: int | None) -> bool:
    if max_age_seconds is None:
        return False
    try:
        fresh = datetime.fromisoformat(freshness_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return True
    if fresh.tzinfo is None:
        fresh = fresh.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - fresh).total_seconds() > max_age_seconds
