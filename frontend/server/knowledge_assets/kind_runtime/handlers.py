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
from .providers import (
    LocalGraphMappingProvider,
    LocalQueryExecutor,
    LocalRetrievalProvider,
    LocalSemanticProvider,
    GraphMappingProvider,
    QueryExecutor,
    RetrievalProvider,
    SemanticProvider,
    monitoring_plan_from_request,
    query_plan_from_request,
)
from .tabular import (
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

    def __init__(self, provider: RetrievalProvider | None = None) -> None:
        self.provider = provider or LocalRetrievalProvider()

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
        query = request.draft_revision.manifest.metadata.description
        hits = self.provider.retrieve(request, query)
        answer, reason = self.provider.answer(request, query, hits)
        state = "ok" if answer else "unable_to_answer"
        answer_text = answer or "无法根据已授权知识来源回答。"
        evidence = [
            _evidence(
                request,
                hit.source_revision_id,
                golden.id,
                hit.chunk_locator,
            )
            for hit in hits[:3]
        ]
        return KindHandlerOutput(
            state=state,
            template="knowledge",
            purpose="answer",
            view_model=KnowledgeViewModel(
                answer=answer_text,
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
                "answer": answer_text,
                "state": state,
                "answerReason": reason,
                "citations": [item.model_dump(mode="json", by_alias=True) for item in evidence],
            },
            evidence=evidence,
        )


class SemanticHandler(KindHandler):
    kind = "semantic"

    def __init__(self, provider: SemanticProvider | None = None) -> None:
        self.provider = provider or LocalSemanticProvider()

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
        semantic = self.provider.build_model(request)
        if semantic.ambiguities:
            return KindHandlerOutput(
                state="schema_drift",
                template="semantic",
                purpose="schema",
                payload={"ambiguities": semantic.ambiguities},
                message="Semantic fields require review before projection.",
            )
        if semantic.dependency_errors:
            return KindHandlerOutput(
                state="validation_failed",
                template="semantic",
                purpose="schema",
                payload={"dependencyErrors": semantic.dependency_errors},
                message="Semantic model dependencies failed validation.",
            )
        cycle = _relationship_cycle(
            [
                f"{relationship.source}.{relationship.target}"
                for relationship in semantic.relationships
            ]
        )
        if cycle:
            return KindHandlerOutput(
                state="validation_failed",
                template="semantic",
                purpose="schema",
                payload={"cycle": cycle},
                message="Semantic relationship cycle detected.",
            )
        metric_refs = [
            field.name for field in semantic.fields if field.role == "measure"
        ]
        dimension_refs = [
            field.name
            for field in semantic.fields
            if field.role in {"dimension", "time"}
        ]
        relationship_refs = [
            f"{relationship.source}.{relationship.target}"
            for relationship in semantic.relationships
        ]
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
                "entities": [{"name": name, "source": golden.id} for name in semantic.entities],
                "metrics": [
                    field.model_dump(mode="json", by_alias=True)
                    for field in semantic.fields
                    if field.role == "measure"
                ],
                "dimensions": [
                    field.model_dump(mode="json", by_alias=True)
                    for field in semantic.fields
                    if field.role == "dimension"
                ],
                "timeSemantics": [
                    field.model_dump(mode="json", by_alias=True)
                    for field in semantic.fields
                    if field.role == "time"
                ],
                "relationships": [
                    relationship.model_dump(mode="json", by_alias=True)
                    for relationship in semantic.relationships
                ],
                "permissions": {"policyRef": request.draft_revision.manifest.spec.policy_ref.uri},
                "editableMdl": semantic.mdl,
            },
            evidence=[_evidence(request, golden.source_revision_refs[0] if golden.source_revision_refs else golden.id, golden.id, "schema:0")],
        )


class AnalysisHandler(KindHandler):
    kind = "analysis"

    def __init__(self, query_executor: QueryExecutor | None = None) -> None:
        self.query_executor = query_executor or LocalQueryExecutor()

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
        try:
            plan = query_plan_from_request(request)
        except ValueError as error:
            return KindHandlerOutput(
                state="no_data",
                template="chart",
                purpose="compare",
                message=str(error),
            )
        try:
            executed = self.query_executor.execute(request, plan)
        except PermissionError as error:
            return KindHandlerOutput(
                state="permission_denied",
                template="chart",
                purpose="compare",
                payload={"deniedFields": str(error).split(",")},
                message="Field-level permission policy rejected query plan.",
            )
        except ValueError as error:
            return KindHandlerOutput(
                state="validation_failed",
                template="chart",
                purpose="compare",
                message=str(error),
            )
        except OverflowError:
            return KindHandlerOutput(
                state="over_budget",
                template="chart",
                purpose="compare",
                payload={"rowCount": len(rows), "maxRows": request.budget.max_rows},
                message="Analysis row budget exceeded.",
            )
        points = [
            (str(row["label"]), float(row["value"]))
            for row in executed["rows"]
            if isinstance(row.get("value"), (int, float))
        ]
        if not points:
            return KindHandlerOutput(
                state="no_data",
                template="chart",
                purpose="compare",
                message="Query plan returned no data.",
            )
        values = [value for _, value in points]
        return KindHandlerOutput(
            state="ok",
            template="chart",
            purpose="compare",
            view_model=ChartViewModel(
                title=request.draft_revision.manifest.metadata.display_name,
                x_field=executed["dimension"] or "result",
                y_field=executed["metric"],
                series=[ChartSeries(name=executed["metric"], points=points)],
                data_ref=golden.storage_ref,
            ),
            payload={
                "query": {
                    "planId": plan.plan_id,
                    "compiled": executed["compiled"],
                    "parameters": plan.filters,
                    "readonly": plan.read_only,
                    "limit": plan.limit,
                    "timeoutMs": plan.timeout_ms or request.budget.timeout_ms,
                },
                "kpis": [
                    {"key": f"sum_{executed['metric']}", "value": sum(values), "unit": _unit_for(executed["metric"])},
                    {"key": "row_count", "value": len(rows), "unit": "rows"},
                ],
                "trends": [{"label": label, "value": value} for label, value in points],
                "nulls": executed["nulls"],
                "dataAsOf": executed["dataAsOf"],
                "source": executed["source"],
            },
            evidence=[_evidence(request, golden.source_revision_refs[0] if golden.source_revision_refs else golden.id, golden.id, f"query:{plan.plan_id}")],
        )


class GraphOntologyHandler(KindHandler):
    kind = "graph_ontology"

    def __init__(self, mapping_provider: GraphMappingProvider | None = None) -> None:
        self.mapping_provider = mapping_provider or LocalGraphMappingProvider()

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
        mapping = self.mapping_provider.build_graph(request)
        node_names = mapping.entities if mapping.entities else [chunk[:48] for chunk in chunks]
        page_size = min(request.budget.max_rows, 500)
        nodes = [
            GraphNode(
                id=f"node-{index}",
                label=name,
                entity_type="metric" if any(name == rel.target for rel in mapping.relationships) else "entity",
            )
            for index, name in enumerate(node_names[:page_size])
        ]
        node_by_label = {node.label: node.id for node in nodes}
        edges = [
            GraphEdge(
                source=node_by_label[relationship.source],
                target=node_by_label[relationship.target],
                relation=relationship.relation,
            )
            for relationship in mapping.relationships
            if relationship.source in node_by_label and relationship.target in node_by_label
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
                "mappingEvidence": mapping.evidence_locators,
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

    def __init__(self, query_executor: QueryExecutor | None = None) -> None:
        self.query_executor = query_executor or LocalQueryExecutor()

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
                state="no_data",
                template="monitoring",
                purpose="monitor",
                message="Monitoring requires at least one metric.",
            )
        plan = monitoring_plan_from_request(request)
        try:
            executed = self.query_executor.execute(request, plan)
        except PermissionError as error:
            return KindHandlerOutput(
                state="permission_denied",
                template="monitoring",
                purpose="monitor",
                payload={"deniedFields": str(error).split(",")},
                message="Field-level permission policy rejected monitoring query plan.",
            )
        except OverflowError:
            return KindHandlerOutput(
                state="over_budget",
                template="monitoring",
                purpose="monitor",
                payload={"rowCount": len(rows), "maxRows": request.budget.max_rows},
                message="Monitoring row budget exceeded.",
            )
        except ValueError as error:
            return KindHandlerOutput(
                state="validation_failed",
                template="monitoring",
                purpose="monitor",
                message=str(error),
            )
        values = [
            (str(row["label"]), float(row["value"]))
            for row in executed["rows"]
            if isinstance(row.get("value"), (int, float))
        ]
        threshold = _threshold(
            getattr(request.draft_revision.manifest.spec.kind_spec, "alert_policy_ref", "")
        )
        latest = values[-1][1] if values else 0.0
        previous = values[-2][1] if len(values) > 1 else latest
        change_rate = 0.0 if previous == 0 else (latest - previous) / abs(previous)
        stale = _stale(golden.freshness_at, request.now, request.budget.freshness_seconds)
        alerts = []
        observations = []
        if threshold is not None and latest >= threshold:
            alerts.append(f"{plan.metric} reached {latest:g}, threshold {threshold:g}")
        if abs(change_rate) >= 0.2 and len(values) > 1:
            alerts.append(f"{plan.metric} changed {change_rate:.0%} since previous point")
        if stale:
            alerts.append("source freshness is stale")
        observation = {
                "metric": plan.metric,
                "latest": latest,
                "previous": previous,
                "changeRate": change_rate,
                "durationSeconds": _duration_seconds(values),
                "freshness": golden.freshness_at,
                "lastGoodRevisionId": golden.id if golden.last_good else None,
            }
        observations.append(observation)
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
                metric_refs=list(getattr(request.draft_revision.manifest.spec.kind_spec, "metric_refs", []) or [plan.metric]),
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


def _null_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            if value in (None, ""):
                counts[key] = counts.get(key, 0) + 1
    return counts


def _duration_seconds(values: list[tuple[str, float]]) -> int:
    if len(values) < 2:
        return 0
    try:
        first = datetime.fromisoformat(values[0][0].replace("Z", "+00:00"))
        last = datetime.fromisoformat(values[-1][0].replace("Z", "+00:00"))
    except ValueError:
        return len(values) - 1
    return max(0, int((last - first).total_seconds()))


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
