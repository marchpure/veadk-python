"""Five explicit Worker 3 Skill kind handlers."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from frontend.server.knowledge_assets.contracts import (
    DashboardChart,
    DashboardDrill,
    DashboardFilter,
    DashboardKpi,
    DashboardViewModel,
    ChartSeries,
    ChartViewModel,
    GraphEdge,
    GraphNode,
    GraphOntologyViewModel,
    KnowledgeCitation,
    KnowledgeViewModel,
    MonitoringViewModel,
    MonitoringObservationView,
    SemanticViewModel,
    SemanticViewField,
    SemanticViewRelationship,
    SopActionProposal,
    SopKindSpec,
    SopStepEvidence,
    SopStepResult,
    SopViewModel,
    ViewCell,
    ViewField,
)

from .models import ExecutionEvidence, KindExecutionRequest, KindHandlerOutput
from .providers import (
    LocalGraphMappingProvider,
    LocalQueryExecutor,
    LocalRetrievalProvider,
    LocalSemanticProvider,
    GraphMappingProvider,
    QueryExecutor,
    RequestBoundSopToolExecutor,
    RetrievalProvider,
    SemanticProvider,
    SopToolExecutor,
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
                "citations": [
                    item.model_dump(mode="json", by_alias=True) for item in evidence
                ],
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
                entities=semantic.entities,
                fields=[
                    SemanticViewField(
                        name=field.name,
                        role=field.role,
                        aggregation=field.aggregation,
                        unit=field.unit,
                        source_field=field.source_field,
                    )
                    for field in semantic.fields
                ],
                relationships=[
                    SemanticViewRelationship(
                        source=item.source,
                        target=item.target,
                        relation=item.relation,
                        join_type=item.join_type,
                        evidence_locator=item.evidence_locator,
                    )
                    for item in semantic.relationships
                ],
                mdl=semantic.mdl,
            ),
            payload={
                "entities": [
                    {"name": name, "source": golden.id} for name in semantic.entities
                ],
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
                "permissions": {
                    "policyRef": request.draft_revision.manifest.spec.policy_ref.uri
                },
                "editableMdl": semantic.mdl,
            },
            evidence=[
                _evidence(
                    request,
                    golden.source_revision_refs[0]
                    if golden.source_revision_refs
                    else golden.id,
                    golden.id,
                    "schema:0",
                )
            ],
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
        dependency_error = _validate_semantic_dependencies(request)
        if dependency_error is not None:
            return KindHandlerOutput(
                state="schema_drift",
                template="dashboard",
                purpose="overview",
                message=dependency_error,
                payload={"semanticDependencyError": dependency_error},
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
        chart = ChartSeries(name=executed["metric"], points=points)
        dashboard = request.draft_revision.manifest.spec.default_renderer == "dashboard"
        presentation = getattr(
            request.draft_revision.manifest.spec.kind_spec, "dashboard", None
        )
        dashboard_title = (
            presentation.title
            if presentation is not None and presentation.title
            else request.draft_revision.manifest.metadata.display_name
        )
        kpi_labels = presentation.kpi_labels if presentation is not None else {}
        filter_fields = (
            presentation.filter_fields
            if presentation is not None and presentation.filter_fields
            else ([executed["dimension"]] if executed["dimension"] else [])
        )
        drill_fields = (
            presentation.drill_fields
            if presentation is not None and presentation.drill_fields
            else [executed["metric"]]
        )
        view_model = (
            DashboardViewModel(
                title=dashboard_title,
                fields=[
                    ViewField(
                        name=key,
                        label=key.replace("_", " ").title(),
                        data_type=_view_type(value),
                    )
                    for key, value in rows[0].items()
                ],
                kpis=[
                    DashboardKpi(
                        key=f"sum_{executed['metric']}",
                        label=kpi_labels.get(
                            f"sum_{executed['metric']}", f"Total {executed['metric']}"
                        ),
                        value=sum(values),
                        unit=_unit_for(executed["metric"]),
                    ),
                    DashboardKpi(
                        key="row_count",
                        label=kpi_labels.get("row_count", "Rows"),
                        value=len(rows),
                        unit="rows",
                    ),
                ],
                charts=[
                    DashboardChart(
                        chart_id=f"{executed['metric']}-by-{executed['dimension'] or 'result'}",
                        title=(
                            presentation.chart_title
                            if presentation is not None and presentation.chart_title
                            else f"{executed['metric']} by {executed['dimension'] or 'result'}"
                        ),
                        x_field=executed["dimension"] or "result",
                        y_field=executed["metric"],
                        series=[chart],
                    )
                ],
                rows=[
                    [ViewCell(field=key, value=value) for key, value in row.items()]
                    for row in rows[: request.budget.max_rows]
                ],
                filters=[
                    DashboardFilter(field=field, operator="in")
                    for field in filter_fields
                ],
                drills=(
                    [
                        DashboardDrill(
                            source_field=executed["dimension"],
                            target_fields=drill_fields,
                        )
                    ]
                    if executed["dimension"]
                    else []
                ),
                data_ref=golden.storage_ref,
            )
            if dashboard
            else ChartViewModel(
                title=request.draft_revision.manifest.metadata.display_name,
                x_field=executed["dimension"] or "result",
                y_field=executed["metric"],
                series=[chart],
                data_ref=golden.storage_ref,
            )
        )
        return KindHandlerOutput(
            state="ok",
            template="dashboard" if dashboard else "chart",
            purpose="overview" if dashboard else "compare",
            view_model=view_model,
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
                    {
                        "key": f"sum_{executed['metric']}",
                        "value": sum(values),
                        "unit": _unit_for(executed["metric"]),
                    },
                    {"key": "row_count", "value": len(rows), "unit": "rows"},
                ],
                "trends": [{"label": label, "value": value} for label, value in points],
                "nulls": executed["nulls"],
                "dataAsOf": executed["dataAsOf"],
                "source": executed["source"],
            },
            evidence=[
                _evidence(
                    request,
                    golden.source_revision_refs[0]
                    if golden.source_revision_refs
                    else golden.id,
                    golden.id,
                    f"query:{plan.plan_id}",
                )
            ],
        )


class SopHandler(KindHandler):
    kind = "sop"

    def __init__(self, tool_executor: SopToolExecutor | None = None) -> None:
        self.tool_executor = tool_executor or RequestBoundSopToolExecutor()

    def execute(self, request: KindExecutionRequest) -> KindHandlerOutput:
        spec = request.draft_revision.manifest.spec.kind_spec
        if not isinstance(spec, SopKindSpec):
            return KindHandlerOutput(
                state="validation_failed",
                template="sop",
                purpose="overview",
                message="SOP execution requires a typed SopKindSpec.",
            )
        errors = _validate_sop_inputs(spec, request.inputs)
        if errors:
            return KindHandlerOutput(
                state="awaiting_input",
                template="sop",
                purpose="overview",
                payload={"validationErrors": errors},
                message="; ".join(errors),
            )
        golden, content = _first_golden(request)
        if golden is None or not content.strip():
            return KindHandlerOutput(
                state="no_data",
                template="sop",
                purpose="overview",
                message="SOP execution requires immutable context evidence.",
            )
        step_results: list[SopStepResult] = []
        evidence: list[ExecutionEvidence] = []
        proposals: list[SopActionProposal] = []
        steps_by_id = {step.id: step for step in spec.steps}
        ordered_ids = [step.id for step in spec.steps]
        cursor = ordered_ids[0]
        visited: set[str] = set()
        while cursor:
            if cursor in visited:
                return KindHandlerOutput(
                    state="validation_failed",
                    template="sop",
                    purpose="overview",
                    message=f"SOP branch cycle detected at {cursor}.",
                )
            visited.add(cursor)
            step = steps_by_id[cursor]
            branch = _evaluate_condition(step.condition, request.inputs)
            if branch is False:
                step_results.append(
                    SopStepResult(
                        step_id=step.id,
                        title=step.title,
                        status="skipped",
                        branch="false",
                        message="Condition was false.",
                    )
                )
                cursor = step.on_false or _next_step(ordered_ids, cursor)
                continue
            step_evidence: list[SopStepEvidence] = []
            if step.tool_ref is not None:
                tool_key = f"{step.tool_ref.tool_id}:{step.tool_ref.operation}"
                if step.tool_ref.risk != "read_only":
                    proposals.append(
                        SopActionProposal(
                            proposal_id=f"proposal-{step.id}",
                            title=step.title,
                            risk=step.tool_ref.risk,
                            challenge=f"Confirm {step.tool_ref.operation} using evidence from {step.id}.",
                            tool_ref=tool_key,
                        )
                    )
                    step_results.append(
                        SopStepResult(
                            step_id=step.id,
                            title=step.title,
                            status="awaiting_confirmation",
                            branch="true" if step.condition else "unconditional",
                            message="External action was not executed during trial run.",
                        )
                    )
                    cursor = (
                        step.on_true if branch is not False else step.on_false
                    ) or _next_step(ordered_ids, cursor)
                    continue
                try:
                    tool_result = self.tool_executor.execute(
                        request,
                        tool_id=step.tool_ref.tool_id,
                        revision=step.tool_ref.revision,
                        operation=step.tool_ref.operation,
                    )
                except LookupError:
                    return KindHandlerOutput(
                        state="awaiting_input",
                        template="sop",
                        purpose="overview",
                        payload={"missingToolResult": tool_key},
                        message=f"Missing real tool result: {tool_key}",
                    )
                step_evidence.append(
                    SopStepEvidence(
                        kind="tool_result",
                        locator=f"tool-result://{tool_key}",
                        summary=json_safe_summary(tool_result),
                    )
                )
            locator = f"local://golden/{golden.storage_ref.sha256}#sop={step.id}"
            step_evidence.append(
                SopStepEvidence(
                    kind="source_citation",
                    locator=locator,
                    summary=step.instruction,
                )
            )
            evidence.append(
                _evidence(
                    request,
                    golden.source_revision_refs[0]
                    if golden.source_revision_refs
                    else golden.id,
                    golden.id,
                    locator,
                )
            )
            step_results.append(
                SopStepResult(
                    step_id=step.id,
                    title=step.title,
                    status="succeeded",
                    branch="true" if step.condition else "unconditional",
                    evidence=step_evidence,
                    message=step.instruction,
                )
            )
            cursor = (
                step.on_true if branch is not False else step.on_false
            ) or _next_step(ordered_ids, cursor)
        recommendation = (
            spec.action_proposal
            if not proposals
            else "Review the generated action proposal and confirm outside the trial run."
        )
        view_model = SopViewModel(
            title=request.draft_revision.manifest.metadata.display_name,
            trigger=spec.trigger,
            scope=spec.scope,
            step_results=step_results,
            recommendation=recommendation,
            outputs={item.name: recommendation for item in spec.outputs},
            action_proposals=proposals,
        )
        return KindHandlerOutput(
            state="ok",
            template="sop",
            purpose="overview",
            view_model=view_model,
            payload={
                "steps": [
                    item.model_dump(mode="json", by_alias=True) for item in step_results
                ],
                "recommendation": recommendation,
                "actionProposals": [
                    item.model_dump(mode="json", by_alias=True) for item in proposals
                ],
                "externalActionsExecuted": False,
            },
            evidence=evidence,
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
        node_names = (
            mapping.entities if mapping.entities else [chunk[:48] for chunk in chunks]
        )
        page_size = min(request.budget.max_rows, 500)
        nodes = [
            GraphNode(
                id=f"node-{index}",
                label=name,
                entity_type="metric"
                if any(name == rel.target for rel in mapping.relationships)
                else "entity",
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
            if relationship.source in node_by_label
            and relationship.target in node_by_label
        ]
        conflicts = duplicate_semantic_names(rows)
        return KindHandlerOutput(
            state="ok",
            template="graph_ontology",
            purpose="explore",
            view_model=GraphOntologyViewModel(
                nodes=nodes,
                edges=edges,
                evidence_ref=golden.storage_ref,
                evidence_locators=mapping.evidence_locators,
                conflicts=conflicts,
            ),
            payload={
                "ontology": {
                    "entities": [
                        node.model_dump(mode="json", by_alias=True) for node in nodes
                    ]
                },
                "relations": [
                    edge.model_dump(mode="json", by_alias=True) for edge in edges
                ],
                "mappingEvidence": mapping.evidence_locators,
                "pagination": {
                    "offset": 0,
                    "limit": page_size,
                    "total": len(node_names),
                },
                "conflicts": conflicts,
                "versionCompare": {
                    "base": request.draft_revision.golden_asset_revision_refs,
                    "current": [golden.id],
                },
            },
            evidence=[
                _evidence(
                    request,
                    golden.source_revision_refs[0]
                    if golden.source_revision_refs
                    else golden.id,
                    golden.id,
                    "ontology:0",
                )
            ],
            warnings=[f"ontology conflict: {item}" for item in conflicts],
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
            getattr(
                request.draft_revision.manifest.spec.kind_spec, "alert_policy_ref", ""
            )
        )
        latest = values[-1][1] if values else 0.0
        previous = values[-2][1] if len(values) > 1 else latest
        change_rate = 0.0 if previous == 0 else (latest - previous) / abs(previous)
        stale = _stale(
            golden.freshness_at, request.now, request.budget.freshness_seconds
        )
        alerts = []
        observations = []
        if threshold is not None and latest >= threshold:
            alerts.append(f"{plan.metric} reached {latest:g}, threshold {threshold:g}")
        if abs(change_rate) >= 0.2 and len(values) > 1:
            alerts.append(
                f"{plan.metric} changed {change_rate:.0%} since previous point"
            )
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
                metric_refs=list(
                    getattr(
                        request.draft_revision.manifest.spec.kind_spec,
                        "metric_refs",
                        [],
                    )
                    or [plan.metric]
                ),
                values=values,
                alerts=alerts,
                data_ref=golden.storage_ref,
                observations=[
                    MonitoringObservationView(
                        metric=plan.metric,
                        latest=latest,
                        previous=previous,
                        change_rate=change_rate,
                        duration_seconds=observation["durationSeconds"],
                        freshness_at=golden.freshness_at,
                        last_good_revision_id=observation["lastGoodRevisionId"],
                    )
                ],
                failure_trace=alerts,
            ),
            payload={
                "observations": observations,
                "alerts": alerts,
                "actionCandidates": action_candidates,
                "reviewLoop": [
                    "data",
                    "action_candidate",
                    "retrospective",
                    "decision",
                    "evidence",
                ],
                "externalActionsExecuted": False,
            },
            evidence=[
                _evidence(
                    request,
                    golden.source_revision_refs[0]
                    if golden.source_revision_refs
                    else golden.id,
                    golden.id,
                    "monitoring:latest",
                )
            ],
        )


HANDLERS: dict[str, KindHandler] = {
    handler.kind: handler
    for handler in (
        KnowledgeHandler(),
        SemanticHandler(),
        AnalysisHandler(),
        SopHandler(),
        GraphOntologyHandler(),
        MonitoringHandler(),
    )
}


def _first_golden(request: KindExecutionRequest):
    asset_id, content = first_content(request.golden_asset_contents)
    golden = next(
        (
            revision
            for revision in request.golden_asset_revisions
            if revision.id == asset_id
        ),
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
        item
        for item in request.golden_asset_revisions
        if item.id == golden_asset_revision_id
    )
    digest = (
        __import__("hashlib")
        .sha256(
            f"{request.trace_id}:{source_revision_id}:{golden_asset_revision_id}:{locator}".encode()
        )
        .hexdigest()[:24]
    )
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


def _view_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _validate_semantic_dependencies(request: KindExecutionRequest) -> str | None:
    for dependency in request.semantic_dependencies:
        if dependency.schema_digest != dependency.current_schema_digest:
            return f"Semantic schema drift: {dependency.skill_revision_id}"
        if dependency.skill_revision_id not in request.downstream_skill_revision_refs:
            return f"Semantic dependency is not pinned: {dependency.skill_revision_id}"
    return None


def _validate_sop_inputs(spec: SopKindSpec, values: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for field in spec.input_fields:
        value = values.get(field.name)
        if field.required and value is None:
            errors.append(f"Missing required input: {field.name}")
            continue
        if value is None:
            continue
        valid = (
            (field.value_type in {"string", "enum"} and isinstance(value, str))
            or (
                field.value_type == "number"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            )
            or (field.value_type == "boolean" and isinstance(value, bool))
        )
        if not valid:
            errors.append(f"Invalid input type: {field.name}")
        if field.value_type == "enum" and value not in field.enum_values:
            errors.append(f"Invalid enum value: {field.name}")
    return errors


def _evaluate_condition(condition: object, values: dict[str, object]) -> bool | None:
    if condition is None:
        return None
    actual = values.get(condition.field)
    expected = condition.value
    operations = {
        "eq": lambda: actual == expected,
        "ne": lambda: actual != expected,
        "gt": lambda: actual is not None and expected is not None and actual > expected,
        "gte": lambda: actual is not None
        and expected is not None
        and actual >= expected,
        "lt": lambda: actual is not None and expected is not None and actual < expected,
        "lte": lambda: actual is not None
        and expected is not None
        and actual <= expected,
        "contains": lambda: str(expected) in str(actual),
        "exists": lambda: actual is not None,
    }
    try:
        return bool(operations[condition.operator]())
    except TypeError:
        return False


def json_safe_summary(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)[:1024]


def _next_step(ordered_ids: list[str], current: str) -> str | None:
    index = ordered_ids.index(current) + 1
    return ordered_ids[index] if index < len(ordered_ids) else None
