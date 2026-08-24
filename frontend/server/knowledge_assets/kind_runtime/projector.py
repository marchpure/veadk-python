"""Worker 3 projection into existing typed Skill view contracts."""

from __future__ import annotations

import hashlib
import html
import json

from frontend.server.knowledge_assets.contracts import (
    ChartViewModel,
    GraphOntologyViewModel,
    KnowledgeViewModel,
    MonitoringViewModel,
    SchemaRef,
    SemanticViewModel,
    SkillResult,
    SkillViewManifest,
    SkillViewRevision,
    StorageRef,
    ViewIntent,
    ViewModel,
)

from .models import ExecutionEvidence, KindExecutionRequest, KindHandlerOutput
from .store import ContentAddressedStore


class SkillViewProjector:
    def __init__(self, store: ContentAddressedStore) -> None:
        self.store = store

    def project(
        self, request: KindExecutionRequest, handler_output: KindHandlerOutput
    ) -> tuple[SkillResult, ViewIntent, SkillViewRevision, StorageRef, StorageRef]:
        if handler_output.view_model is None:
            raise ValueError("successful projection requires a typed ViewModel")

        result_payload = {
            "schemaVersion": "knowledge-assets.worker3.skill-result.v1",
            "state": handler_output.state,
            "kind": request.draft_revision.manifest.spec.kind,
            "skillRevisionId": request.draft_revision.id,
            "caller": {
                "callerId": request.caller_id,
                "workspaceId": request.workspace_id,
            },
            "dataRevisionRefs": [item.id for item in request.golden_asset_revisions],
            "dataAccessRevisionRefs": request.data_access_revision_refs,
            "downstreamSkillRevisionRefs": request.downstream_skill_revision_refs,
            "freshness": request.freshness_at,
            "payload": handler_output.payload,
            "evidence": [
                item.model_dump(mode="json", by_alias=True)
                for item in handler_output.evidence
            ],
        }
        result_ref = self.store.write_json("results", result_payload)
        evidence_ref = self.store.write_json(
            "evidence",
            {
                "traceId": request.trace_id,
                "items": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in handler_output.evidence
                ],
            },
        )
        html_ref = self.store.write_bytes(
            "views",
            trusted_html(handler_output.template, handler_output.view_model),
            media_type="text/html",
            suffix=".html",
        )
        skill = request.draft_revision
        skill_result = SkillResult(
            id=f"result-{result_ref.sha256[:24]}",
            skill_id=skill.skill_id,
            skill_revision=skill.revision,
            kind=skill.manifest.spec.kind,
            output_schema_ref=skill.manifest.spec.contract.output_schema_ref,
            result_ref=result_ref,
            source_revision_refs=_source_refs(request, handler_output.evidence),
            golden_asset_revision_refs=[item.id for item in request.golden_asset_revisions],
            trace_id=request.trace_id,
            freshness_at=request.freshness_at,
        )
        view_intent = ViewIntent(
            id=f"view-intent-{result_ref.sha256[:24]}",
            skill_id=skill.skill_id,
            skill_revision=skill.revision,
            template=handler_output.template,
            purpose=handler_output.purpose,
            result_ref=result_ref.uri,
        )
        view_model_ref = self.store.write_json(
            "view-models",
            handler_output.view_model.model_dump(mode="json", by_alias=True),
        )
        view_id_material = json.dumps(
            {
                "skillRevisionId": skill.id,
                "result": result_ref.sha256,
                "view": html_ref.sha256,
                "model": view_model_ref.sha256,
            },
            sort_keys=True,
        ).encode()
        view_digest = hashlib.sha256(view_id_material).hexdigest()
        view_revision = SkillViewRevision(
            id=f"view-{view_digest[:24]}",
            skill_revision_id=f"{skill.skill_id}:{skill.revision}",
            revision=1,
            manifest=SkillViewManifest(
                id=f"view-manifest-{view_digest[:24]}",
                skill_revision_id=f"{skill.skill_id}:{skill.revision}",
                renderer_ref=f"renderer://{handler_output.template}/v1",
                view_model_schema_ref=SchemaRef(
                    uri=view_model_ref.uri,
                    version="1",
                    sha256=view_model_ref.sha256,
                ),
                allowed_components=[
                    "SkillViewShell",
                    f"{handler_output.template.title().replace('_', '')}View",
                ],
            ),
            intent=view_intent,
            view_model=handler_output.view_model,
            result_ref=html_ref,
            created_at=request.now,
        )
        return skill_result, view_intent, view_revision, evidence_ref, html_ref


def trusted_html(template: str, view_model: ViewModel) -> bytes:
    title = html.escape(template.replace("_", " ").title())
    body = _text_alternative(view_model)
    return (
        "<!doctype html>"
        f'<article data-renderer="{html.escape(template)}-v1" '
        'data-csp="trusted-renderer-v1" role="region" '
        f'aria-label="{title}">'
        f"<h1>{title}</h1>"
        f'<pre data-node-kind="text-alternative">{html.escape(body)}</pre>'
        "</article>"
    ).encode("utf-8")


def _text_alternative(view_model: ViewModel) -> str:
    if isinstance(view_model, KnowledgeViewModel):
        citations = ", ".join(citation.locator for citation in view_model.citations)
        return f"{view_model.answer}\nCitations: {citations}"
    if isinstance(view_model, SemanticViewModel):
        return json.dumps(
            {
                "metrics": view_model.metric_refs,
                "dimensions": view_model.dimension_refs,
                "relationships": view_model.relationship_refs,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    if isinstance(view_model, ChartViewModel):
        return json.dumps(
            {
                "x": view_model.x_field,
                "y": view_model.y_field,
                "series": [
                    series.model_dump(mode="json", by_alias=True)
                    for series in view_model.series
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    if isinstance(view_model, GraphOntologyViewModel):
        return json.dumps(
            {
                "nodes": [node.model_dump(mode="json", by_alias=True) for node in view_model.nodes],
                "edges": [edge.model_dump(mode="json", by_alias=True) for edge in view_model.edges],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    if isinstance(view_model, MonitoringViewModel):
        return json.dumps(
            {
                "metricRefs": view_model.metric_refs,
                "values": view_model.values,
                "alerts": view_model.alerts,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    return view_model.model_dump_json()


def _source_refs(
    request: KindExecutionRequest, evidence: list[ExecutionEvidence]
) -> list[str]:
    refs = [item.source_revision_id for item in evidence]
    if refs:
        return refs
    fallback: list[str] = []
    for golden in request.golden_asset_revisions:
        fallback.extend(golden.source_revision_refs)
    return fallback
