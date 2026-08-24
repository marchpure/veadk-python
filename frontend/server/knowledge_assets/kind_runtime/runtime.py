"""Unified Worker 3 runtime for explicit Skill kind execution."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from frontend.server.knowledge_assets.contracts import SkillKind

from .handlers import HANDLERS
from .models import (
    ExecutionTrace,
    KindExecutionRequest,
    KindHandlerOutput,
    SkillKindExecutionRecord,
)
from .projector import SkillViewProjector
from .repository import KindRuntimeRepository
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

    def __init__(
        self,
        store: ContentAddressedStore | None = None,
        *,
        repository: KindRuntimeRepository | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.store = store or ContentAddressedStore()
        self.projector = SkillViewProjector(self.store)
        self.repository = repository
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="knowledge-kind-runtime"
        )

    def execute(self, request: KindExecutionRequest) -> SkillKindExecutionRecord:
        return self._execute(request)

    def retry(
        self, request: KindExecutionRequest, *, retry_of_operation_id: str
    ) -> SkillKindExecutionRecord:
        original = self.repository.get(retry_of_operation_id) if self.repository else None
        if original is None:
            operation_id = self._operation_id(request)
            if self.repository is not None:
                replay = self.repository.begin(
                    operation_id, request.model_dump(mode="json", by_alias=True)
                )
                if replay is not None:
                    return replay
            trace = ExecutionTrace(
                trace_id=request.trace_id,
                steps=["queued", "retry-source-missing"],
                started_at=request.now,
                finished_at=request.now,
            )
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state="validation_failed",
                handler="none",
                message="Retry requires a persisted source operation.",
                retry_of_operation_id=retry_of_operation_id,
            ))
        if original.status not in {"failed", "awaiting_input", "cancelled"}:
            operation_id = self._operation_id(request)
            if self.repository is not None:
                replay = self.repository.begin(
                    operation_id, request.model_dump(mode="json", by_alias=True)
                )
                if replay is not None:
                    return replay
            trace = ExecutionTrace(
                trace_id=request.trace_id,
                steps=["queued", "retry-source-not-retryable"],
                started_at=request.now,
                finished_at=request.now,
            )
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state="validation_failed",
                handler="none",
                message="Only failed, awaiting-input, or cancelled operations are retryable.",
                retry_of_operation_id=retry_of_operation_id,
            ))
        return self._execute(request, retry_of_operation_id=retry_of_operation_id)

    def cancel(self, idempotency_key: str) -> None:
        if self.repository is None:
            return
        self.repository.mark_cancel_requested(
            self.repository.operation_id_for_key(idempotency_key)
        )

    def recover_incomplete(self) -> list[str]:
        if self.repository is None:
            return []
        return self.repository.recover_incomplete()

    def _execute(
        self,
        request: KindExecutionRequest,
        *,
        retry_of_operation_id: str | None = None,
    ) -> SkillKindExecutionRecord:
        operation_id = self._operation_id(request)
        trace = ExecutionTrace(
            trace_id=request.trace_id,
            steps=["queued", "resolve-draft-revision"],
            started_at=request.now,
        )
        if self.repository is not None:
            replay = self.repository.begin(
                operation_id, request.model_dump(mode="json", by_alias=True)
            )
            if replay is not None:
                return replay
        if request.cancel_requested:
            trace.steps.append("cancelled-before-run")
            record = self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="cancelled",
                state="cancelled",
                handler="none",
                message="Execution was cancelled before handler dispatch.",
                retry_of_operation_id=retry_of_operation_id,
            )
            return self._complete(record)
        kind = request.draft_revision.manifest.spec.kind
        handler = HANDLERS.get(kind)
        if handler is None:
            trace.steps.append(f"unsupported-kind:{kind}")
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state="validation_failed",
                handler="none",
                message=f"Unsupported Worker 3 Skill kind: {kind}",
                retry_of_operation_id=retry_of_operation_id,
            ))
        if not request.golden_asset_revisions:
            trace.steps.append("awaiting-golden-asset")
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="awaiting_input",
                state="no_data",
                handler=handler.__class__.__name__,
                message="Execution requires at least one Golden Asset revision.",
                retry_of_operation_id=retry_of_operation_id,
            ))
        byte_count = sum(len(value.encode("utf-8")) for value in request.golden_asset_contents.values())
        if byte_count > request.budget.max_bytes:
            trace.steps.append("budget-bytes-exceeded")
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state="over_budget",
                handler=handler.__class__.__name__,
                message="Execution byte budget exceeded.",
                retry_of_operation_id=retry_of_operation_id,
            ))
        started = time.perf_counter()
        trace.steps.append(f"execute-{kind}")
        future = self._executor.submit(handler.execute, request)
        try:
            deadline = time.monotonic() + (request.budget.timeout_ms / 1000)
            while True:
                if self.repository is not None and self.repository.cancel_requested(operation_id):
                    trace.steps.append("cancelled-during-run")
                    future.cancel()
                    return self._complete(self._terminal(
                        request,
                        operation_id=operation_id,
                        trace=trace,
                        status="cancelled",
                        state="cancelled",
                        handler=handler.__class__.__name__,
                        message="Execution was cancelled while handler was running.",
                        retry_of_operation_id=retry_of_operation_id,
                    ))
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    raise TimeoutError()
                output = future.result(timeout=min(0.05, remaining_seconds))
                break
        except TimeoutError:
            trace.steps.append("timeout")
            future.cancel()
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state="timeout",
                handler=handler.__class__.__name__,
                message="Execution timeout exceeded.",
                retry_of_operation_id=retry_of_operation_id,
            ))
        except Exception as error:
            trace.steps.append("handler-exception")
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state="validation_failed",
                handler=handler.__class__.__name__,
                message=str(error),
                retry_of_operation_id=retry_of_operation_id,
            ))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if elapsed_ms > request.budget.timeout_ms:
            trace.steps.append("timeout")
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state="timeout",
                handler=handler.__class__.__name__,
                message="Execution timeout exceeded.",
                retry_of_operation_id=retry_of_operation_id,
            ))
        if self.repository is not None and self.repository.cancel_requested(operation_id):
            trace.steps.append("cancelled-during-run")
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="cancelled",
                state="cancelled",
                handler=handler.__class__.__name__,
                message="Execution was cancelled while handler was running.",
                retry_of_operation_id=retry_of_operation_id,
            ))
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
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status="failed",
                state=output.state,
                handler=handler.__class__.__name__,
                message=output.message,
                output=output,
                retry_of_operation_id=retry_of_operation_id,
            ))
        if output.state in {"no_data", "unable_to_answer"}:
            status = "awaiting_input" if output.view_model is None else "succeeded"
        else:
            status = "succeeded"
        if output.view_model is None:
            return self._complete(self._terminal(
                request,
                operation_id=operation_id,
                trace=trace,
                status=status,
                state=output.state,
                handler=handler.__class__.__name__,
                message=output.message,
                output=output,
                retry_of_operation_id=retry_of_operation_id,
            ))
        skill_result, view_intent, view_revision, evidence_ref, _ = self.projector.project(
            request, output
        )
        monitoring_lifecycle = None
        if kind == "monitoring":
            from .models import (
                MonitoringActionCandidate,
                MonitoringAlert,
                MonitoringLifecycle,
                MonitoringObservation,
            )

            observations = [
                MonitoringObservation(
                    id=f"observation-{index}",
                    metric=str(item["metric"]),
                    value=float(item["latest"]),
                    previous_value=float(item["previous"]) if item.get("previous") is not None else None,
                    change_rate=float(item["changeRate"]) if item.get("changeRate") is not None else None,
                    duration_seconds=int(item.get("durationSeconds", 0)),
                    freshness_at=str(item["freshness"]),
                    last_good_revision_id=item.get("lastGoodRevisionId"),
                    evidence_locator="monitoring:latest",
                )
                for index, item in enumerate(output.payload.get("observations", []))
                if isinstance(item, dict)
            ]
            alerts = [
                MonitoringAlert(
                    id=f"alert-{index}",
                    observation_id=observations[0].id if observations else "observation-0",
                    reason=str(reason),
                    opened_at=request.now,
                )
                for index, reason in enumerate(output.payload.get("alerts", []))
            ]
            action_candidates = [
                MonitoringActionCandidate(
                    id=f"action-candidate-{index}",
                    alert_id=alerts[0].id if alerts else "alert-0",
                    title=str(item.get("title", "Review monitoring alert")),
                    preview_only=bool(item.get("previewOnly", True)),
                    evidence_locator=str(item.get("evidenceLocator", "monitoring:latest")),
                )
                for index, item in enumerate(output.payload.get("actionCandidates", []))
                if isinstance(item, dict)
            ]
            monitoring_lifecycle = MonitoringLifecycle(
                operation_id=operation_id,
                observations=observations,
                alerts=alerts,
                action_candidates=action_candidates,
                external_actions_executed=False,
            )
        trace = trace.model_copy(update={"finished_at": request.now})
        trace_ref = self.store.write_json(
            "traces", trace.model_dump(mode="json", by_alias=True)
        )
        return self._complete(SkillKindExecutionRecord(
            operation_id=operation_id,
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
            retry_of_operation_id=retry_of_operation_id,
            monitoring_lifecycle=monitoring_lifecycle,
            message=output.message,
        ))

    def _terminal(
        self,
        request: KindExecutionRequest,
        *,
        operation_id: str,
        trace: ExecutionTrace,
        status: str,
        state: str,
        handler: str,
        message: str | None,
        output: KindHandlerOutput | None = None,
        retry_of_operation_id: str | None = None,
    ) -> SkillKindExecutionRecord:
        trace = trace.model_copy(update={"finished_at": request.now})
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
            operation_id=operation_id,
            status=status,  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            draft_revision_id=request.draft_revision.id,
            trace_ref=trace_ref,
            evidence_ref=evidence_ref,
            trace=trace,
            handler=handler,
            idempotency_key=request.idempotency_key,
            retry_of_operation_id=retry_of_operation_id,
            message=message,
        )

    def _complete(self, record: SkillKindExecutionRecord) -> SkillKindExecutionRecord:
        if record.trace.finished_at is None:
            record = record.model_copy(
                update={
                    "trace": record.trace.model_copy(
                        update={"finished_at": record.trace.started_at}
                    )
                }
            )
        if self.repository is None:
            return record
        return self.repository.complete(record)

    def _operation_id(self, request: KindExecutionRequest) -> str:
        if self.repository is not None:
            return self.repository.operation_id_for_key(request.idempotency_key)
        import hashlib

        return "w3op-" + hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:24]
