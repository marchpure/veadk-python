import type { ConversationTurnModel } from "../assistant/assistant-model";

const STATUS_LABEL: Record<ConversationTurnModel["status"], string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function isToday(value: string): boolean {
  return new Date(value).toDateString() === new Date().toDateString();
}

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>;
}

export function InvocationRail({
  turns,
  activeInvocationId,
  onSelect,
  onClose,
}: {
  turns: ConversationTurnModel[];
  activeInvocationId?: string;
  onSelect: (invocationId: string) => void;
  onClose?: () => void;
}) {
  const groups = [
    ["今天", turns.filter((turn) => isToday(turn.createdAt))],
    ["更早", turns.filter((turn) => !isToday(turn.createdAt))],
  ] as const;
  return (
    <aside className="kw-invocation-rail" aria-label="会话与运行记录">
      <header>
        <strong>会话与运行</strong>
        {onClose ? <button type="button" aria-label="关闭会话列表" onClick={onClose}><CloseIcon /></button> : null}
      </header>
      <div className="kw-session-gap" role="note">当前服务暂不支持独立新会话</div>
      <div className="kw-invocation-list">
        {groups.map(([label, entries]) => entries.length ? (
          <section key={label}>
            <h3>{label}</h3>
            {entries.map((turn) => (
              <button
                type="button"
                key={turn.invocationId}
                className={activeInvocationId === turn.invocationId ? "is-active" : ""}
                onClick={() => onSelect(turn.invocationId)}
              >
                <span>{turn.userMessage || "生成当前 Skill"}</span>
                <small className={`is-${turn.status}`}>{STATUS_LABEL[turn.status]}</small>
              </button>
            ))}
          </section>
        ) : null)}
        {!turns.length ? <div className="kw-invocation-empty">第一条真实消息发送后会显示在这里。</div> : null}
      </div>
    </aside>
  );
}
