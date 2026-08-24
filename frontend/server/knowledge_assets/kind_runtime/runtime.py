"""Unified Worker 3 runtime for explicit Skill kind execution."""

from __future__ import annotations

import time

from frontend.server.knowledge_assets.contracts import SkillKind

from .handlers import HANDLERS
from .models import (
    ExecutionTrace,
    KindExecutionRequest,
    KindHandlerOutput,
    SkillKindExecutionRecord,
)
from .projector import SkillViewProjector
from .store import ContentAddressedStore


class KindRuntime:
    """Dispatches exactly the Worker 3 owned execution kinds.

    The runtime is deliberately explicit. It refuses unsupported kinds instead
    of accepting a universal artifact payload.
    """

    supported_kinds: tuple[SkillKind, ...] = (
        "knowledge",
        "semantic",
        "analysis",
        "graph_ontology",
        "monitoring",
    )

    def __init__(self, store: ContentAddressedStore | None = None) -> None:
        self.store = store or ContentAddressedStore()
        self.projector = SkillViewProjector(self.store)

    def execute(self, request: KindExecutionRequest) -> SkillKindExecutionRecord:
        trace = ExecutionTrace(
            trace_id=request.trace_id,
            steps=["queued", "resolve-draft-revision"],
        )
        if request.cancel_requested:
            trace.steps.append("cancelled-before-run")
            return self._terminal(
                request,
                trace=trace,
                status="cancelled",
                state="cancelled",
                handler="none",
                message="Execution was cancelled before handler dispatch.",
            )
        kind = request.draft_revision.manifest.spec.kind
        handler = HANDLERS.get(kind)
        if handler is None:
            trace.steps.append(f"unsupported-kind:{kind}")
            return self._terminal(
                request,
                trace=trace,
                status="failed",
                state="validation_failed",
                handler="none",
                message=f"Unsupported Worker 3 Skill kind: {kind}",
            )
        if not request.golden_asset_revisions:
            trace.steps.append("awaiting-golden-asset")
            return self._terminal(
                request,
                trace=trace,
                status="awaiting_input",
                state="no_data",
                handler=handler.__class__.__name__,
                message="Execution requires at least one Golden Asset revision.",
            )
        byte_count = sum(len(value.encode("utf-8")) for value in request.golden_asset_contents.values())
        if byte_count > request.budget.max_bytes:
            trace.steps.append("budget-bytes-exceeded")
            return self._terminal(
                request,
                trace=trace,
                status="failed",
                state="over_budget",
                handler=handler.__class__.__name__,
                message="Execution byte budget exceeded.",
            )
        started = time.perf_counter()
        trace.steps.append(f"execute-{kind}")
        output = handler.execute(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if elapsed_ms > request.budget.timeout_ms:
            trace.steps.append("timeout")
            return self._terminal(
                request,
                trace=trace,
                status="failed",
                state="timeout",
                handler=handler.__class__.__name__,
                message="Execution timeout exceeded.",
            )
        trace.steps.extend(
            ["project-view-model", "write-content-addressed-revisions"]
        )
        trace.warnings.extend(output.warnings)
        if output.state in {
            "permission_denied",
            "schema_drift",
            "validation_failed",
            "timeout",
            "over_budget",
            "credential_blocked",
        }:
            return self._terminal(
                request,
                trace=trace,
                status="failed",
                state=output.state,
                handler=handler.__class__.__name__,
                message=output.message,
                output=output,
            )
        if output.state in {"no_data", "unable_to_answer"}:
            status = "awaiting_input" if output.view_model is None else "succeeded"
        else:
            status = "succeeded"
        if output.view_model is None:
            return self._terminal(
                request,
                trace=trace,
                status=status,
                state=output.state,
                handler=handler.__class__.__name__,
                message=output.message,
                output=output,
            )
        skill_result, view_intent, view_revision, evidence_ref, _ = self.projector.project(
            request, output
        )
        trace_ref = self.store.write_json(
            "traces", trace.model_dump(mode="json", by_alias=True)
        )
        return SkillKindExecutionRecord(
            status=status,
            state=output.state,
            draft_revision_id=request.draft_revision.id,
            skill_result=skill_result,
            view_intent=view_intent,
            skill_view_revision=view_revision,
            result_payload_ref=skill_result.result_ref,
            trace_ref=trace_ref,
            evidence_ref=evidence_ref,
            trace=trace,
            handler=handler.__class__.__name__,
            idempotency_key=request.idempotency_key,
            message=output.message,
        )

    def _terminal(
        self,
        request: KindExecutionRequest,
        *,
        trace: ExecutionTrace,
        status: str,
        state: str,
        handler: str,
        message: str | None,
        output: KindHandlerOutput | None = None,
    ) -> SkillKindExecutionRecord:
        trace_ref = self.store.write_json(
            "traces", trace.model_dump(mode="json", by_alias=True)
        )
        evidence_ref = self.store.write_json(
            "evidence",
            {
                "traceId": trace.trace_id,
                "state": state,
                "message": message,
                "evidence": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in (output.evidence if output else [])
                ],
            },
        )
        return SkillKindExecutionRecord(
            status=status,  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            draft_revision_id=request.draft_revision.id,
            trace_ref=trace_ref,
            evidence_ref=evidence_ref,
            trace=trace,
            handler=handler,
            idempotency_key=request.idempotency_key,
            message=message,
        )
