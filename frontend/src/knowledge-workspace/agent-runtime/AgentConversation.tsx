import { FormEvent, KeyboardEvent, useState } from "react";
import type { AgentRuntimeContext, TimelineState } from "./contracts";
import type { AgentRuntimeControllerOptions } from "./controller";
import { AgentTimeline } from "./AgentTimeline";
import { useAgentRuntime } from "./useAgentRuntime";

export interface AgentConversationProps {
  context?: AgentRuntimeContext;
  baseUrl?: string;
  className?: string;
  placeholder?: string;
  title?: string;
  storageKey?: string;
  controllerOptions?: Omit<
    AgentRuntimeControllerOptions,
    "baseUrl" | "snapshotStore"
  >;
}

export function AgentConversation({
  context,
  baseUrl,
  className = "",
  placeholder = "向 Agent 提问，或描述你想创建的 Skill…",
  title = "Agent",
  storageKey,
  controllerOptions,
}: AgentConversationProps) {
  const runtime = useAgentRuntime({
    ...controllerOptions,
    context,
    baseUrl,
    storageKey,
  });
  const [input, setInput] = useState("");
  const [submissionError, setSubmissionError] = useState<string>();
  const [completedTurns, setCompletedTurns] = useState<
    { prompt: string; state: TimelineState }[]
  >([]);
  const running = runtime.active
    || ["connecting", "running", "reconnecting", "stopping"].includes(
      runtime.state.status,
    );

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const prompt = input.trim();
    if (!prompt || running) return;
    setSubmissionError(undefined);
    setInput("");
    const previousPrompt = runtime.state.userPrompt;
    if (
      previousPrompt
      && runtime.state.operationId
      && runtime.state.operationId !== "pending"
      && !["idle", "connecting", "running", "reconnecting", "stopping"].includes(
        runtime.state.status,
      )
    ) {
      setCompletedTurns((turns) => [
        ...turns,
        { prompt: previousPrompt, state: runtime.state },
      ]);
    }
    try {
      await runtime.send(prompt);
    } catch (error) {
      setInput(prompt);
      setSubmissionError(
        error instanceof Error ? error.message : "消息发送失败，请重试。",
      );
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter"
      && !event.shiftKey
      && !event.nativeEvent.isComposing
      && event.nativeEvent.keyCode !== 229
    ) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <section className={`agent-conversation ${className}`} aria-label={title}>
      <header className="agent-conversation__header">
        <div>
          <span>Knowledge Workspace</span>
          <h1>{title}</h1>
        </div>
        {runtime.state.operationId
          && runtime.state.operationId !== "pending"
          && <code>{runtime.state.operationId}</code>}
      </header>
      <div className="agent-conversation__body">
        {completedTurns.map((turn) => (
          <article
            className="agent-conversation__turn"
            key={turn.state.operationId}
          >
            <article className="agent-user-message">
              <span>你</span>
              <p>{turn.prompt}</p>
            </article>
            <article className="agent-assistant-message">
              <span className="agent-assistant-message__label">Agent</span>
              <AgentTimeline state={turn.state} />
            </article>
          </article>
        ))}
        {!runtime.state.userPrompt
          && runtime.state.events.length === 0
          && completedTurns.length === 0 && (
          <div className="agent-conversation__empty">
            <strong>从一个问题开始</strong>
            <span>回答、工具进度与 Skill revision 会在同一轮中持续更新。</span>
          </div>
        )}
        {runtime.state.userPrompt && (
          <article className="agent-user-message">
            <span>你</span>
            <p>{runtime.state.userPrompt}</p>
          </article>
        )}
        {(runtime.state.userPrompt || runtime.state.events.length > 0) && (
          <article className="agent-assistant-message agent-assistant-message--active">
            <span className="agent-assistant-message__label">Agent</span>
            <AgentTimeline
              state={runtime.state}
              onStop={() => void runtime.stop()}
              onRetry={() => void runtime.retry()}
              onResume={() => void runtime.resume()}
            />
          </article>
        )}
      </div>
      <form className="agent-composer" onSubmit={submit}>
        {submissionError && (
          <p className="agent-composer__error" role="alert">{submissionError}</p>
        )}
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={running ? "Agent 正在处理当前请求…" : placeholder}
          aria-label="发送给 Agent 的消息"
          disabled={running}
          rows={3}
        />
        <div className="agent-composer__footer">
          <span>{running ? "本轮完成或停止后可继续发送" : "Enter 发送 · Shift+Enter 换行"}</span>
          {running ? (
            <button
              type="button"
              className="agent-button agent-button--danger"
              onClick={() => void runtime.stop()}
              disabled={runtime.state.status === "stopping"}
            >
              {runtime.state.status === "stopping" ? "正在停止" : "停止"}
            </button>
          ) : (
            <button
              type="submit"
              className="agent-button agent-button--primary"
              disabled={!input.trim()}
            >
              发送
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
