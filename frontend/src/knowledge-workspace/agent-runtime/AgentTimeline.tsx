import type { AgentTimelineProps } from "./contracts";
import { ActivityStatus } from "./ActivityStatus";
import { ArtifactRevisionCard } from "./ArtifactRevisionCard";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { PlanSummary } from "./PlanSummary";
import { ToolCallCard } from "./ToolCallCard";
import { useStickToBottom } from "./useStickToBottom";
import "./agent-runtime.css";

export function AgentTimeline({
  state,
  onStop,
  onRetry,
  onResume,
  className = "",
}: AgentTimelineProps) {
  const {
    containerRef,
    contentRef,
    following,
    onScroll,
    resume,
  } = useStickToBottom(state.lastEventId);
  const running = state.status === "connecting" || state.status === "running";
  const provenanceEvent = [...state.events].reverse().find((event) =>
    event.session_id || event.trace_id
  );
  const resolvedContext = state.events.find(
    (event) => event.type === "context.resolved",
  );
  const finalAnswer = [...state.events].reverse().find(
    (event) => event.type === "answer.final",
  );
  const citationCount = Array.isArray(finalAnswer?.payload.citations)
    ? finalAnswer.payload.citations.length
    : 0;
  return (
    <section className={`agent-timeline ${className}`} aria-label="Agent activity">
      <div
        ref={containerRef}
        className="agent-timeline__scroll"
        onScroll={onScroll}
        aria-live="polite"
        aria-busy={running}
      >
        <div ref={contentRef} className="agent-timeline__content">
          <ActivityStatus state={state} />
          <PlanSummary steps={state.plan} />
          {state.tools.map((tool) => <ToolCallCard key={tool.id} tool={tool} />)}
          {state.answerText && (
            <div className="agent-answer" aria-label="Assistant answer">
              <MarkdownAnswer
                content={state.answerText}
                streaming={running && !state.finalAnswer}
              />
            </div>
          )}
          {state.artifacts.map((artifact) => (
            <ArtifactRevisionCard key={artifact.id} artifact={artifact} />
          ))}
          {provenanceEvent && (
            <div className="agent-provenance" aria-label="来源与运行信息">
              <span>
                会话 {provenanceEvent.session_id ?? "已建立"}
              </span>
              <span>
                Trace {provenanceEvent.trace_id ?? "已记录"}
              </span>
              {resolvedContext && (
                <span>
                  来源摘要：已授权上下文 {String(
                    resolvedContext.payload.resource_count ?? "若干",
                  )} 项
                  {citationCount > 0 ? ` · 引用 ${citationCount} 项` : ""}
                </span>
              )}
            </div>
          )}
          {state.warning && (
            <div className="agent-notice" role="status">{state.warning}</div>
          )}
          {state.error && (
            <div className="agent-error" role="alert">
              <strong>{state.error.message}</strong>
              {state.error.requestId && <small>请求 ID：{state.error.requestId}</small>}
            </div>
          )}
        </div>
      </div>
      <div className="agent-timeline__actions">
        {running && onStop && (
          <button type="button" onClick={onStop}>Stop</button>
        )}
        {state.status === "failed" && onRetry && (
          <button type="button" onClick={onRetry}>重试</button>
        )}
        {state.status === "cancelled" && onRetry && (
          <button type="button" onClick={onRetry}>重新运行</button>
        )}
        {state.status === "disconnected" && onResume && (
          <button type="button" onClick={onResume}>继续连接</button>
        )}
        {!following && (
          <button type="button" onClick={resume}>
            回到底部
          </button>
        )}
      </div>
    </section>
  );
}
