import { ActivityTimeline } from "./ActivityTimeline";
import { AssistantMessage } from "./AssistantMessage";
import { RunSummary } from "./RunSummary";
import type { ConversationTurnModel } from "./assistant-model";

export function ConversationTurn({
  turn,
  onReconnect,
  onRetry,
}: {
  turn: ConversationTurnModel;
  onReconnect: (turn: ConversationTurnModel) => void;
  onRetry: (turn: ConversationTurnModel) => void;
}) {
  const failed = turn.status === "failed";
  return (
    <article className="kw-conversation-turn" data-invocation-id={turn.invocationId}>
      <div className="kw-user-message">{turn.userMessage || "生成当前 Skill"}</div>
      <div className="kw-assistant-response">
        <ActivityTimeline activities={turn.activities} status={turn.status} />
        <AssistantMessage
          content={turn.assistantContent}
          streaming={turn.status === "running"}
        />
        {turn.stateUpdate && !turn.stateUpdate.stateReady ? (
          turn.stateUpdate.stateReady === false ? (
            <div className="kw-persistence-error" role="alert">
              {turn.stateUpdate.errorSummary || "运行状态保存失败"}
            </div>
          ) : null
        ) : null}
        {turn.connectionState === "disconnected" ? (
          <div className="kw-run-recovery" role="alert">
            <span>连接已中断，已完成内容会保留。</span>
            <button type="button" onClick={() => onReconnect(turn)}>继续接收</button>
          </div>
        ) : null}
        {failed ? (
          <div className="kw-run-recovery" role="alert">
            <span>{turn.error?.message || "本次运行失败。"}</span>
            {turn.error?.retryable !== false
              ? <button type="button" onClick={() => onRetry(turn)}>重试本次运行</button>
              : null}
          </div>
        ) : null}
        <RunSummary turn={turn} />
      </div>
    </article>
  );
}
