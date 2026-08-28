import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type UIEvent,
} from "react";
import { ConversationTurn } from "./ConversationTurn";
import type { ConversationTurnModel } from "./assistant-model";

export function AssistantPanel({
  turns,
  busy,
  onSend,
  onCancel,
  onReconnect,
  onRetry,
}: {
  turns: ConversationTurnModel[];
  busy: boolean;
  onSend: (message: string, intent: "update" | "run") => Promise<void>;
  onCancel: () => Promise<void>;
  onReconnect: (turn: ConversationTurnModel) => void;
  onRetry: (turn: ConversationTurnModel) => void;
}) {
  const [message, setMessage] = useState("");
  const [following, setFollowing] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  const submitting = useRef(false);
  const activeTurn = [...turns].reverse().find(
    (turn) => turn.status === "queued" || turn.status === "running",
  );

  useEffect(() => {
    if (!following || !scroller.current) return;
    scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [following, turns]);

  const submit = async (intent: "update" | "run") => {
    const value = message.trim();
    if (!value || busy || activeTurn || submitting.current) return;
    submitting.current = true;
    setMessage("");
    setFollowing(true);
    try {
      await onSend(value, intent);
    } finally {
      submitting.current = false;
    }
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit("run");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== "Enter"
      || event.shiftKey
      || composing.current
      || event.nativeEvent.isComposing
      || event.nativeEvent.keyCode === 229
    ) {
      return;
    }
    event.preventDefault();
    void submit("run");
  };
  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const node = event.currentTarget;
    setFollowing(node.scrollHeight - node.scrollTop - node.clientHeight < 48);
  };

  return (
    <aside className="kw-chat" aria-label="分析助手">
      <div className="kw-chat-heading">
        <div className="kw-chat-title">分析助手</div>
        {activeTurn ? (
          <button type="button" onClick={() => void onCancel()} disabled={busy}>停止</button>
        ) : null}
      </div>
      <div className="kw-timeline" ref={scroller} onScroll={onScroll} aria-live="polite">
        {!turns.length ? (
          <div className="kw-chat-empty">输入任务后，执行过程和最终回答会保存在这里。</div>
        ) : turns.map((turn) => (
          <ConversationTurn
            key={turn.invocationId}
            turn={turn}
            onReconnect={onReconnect}
            onRetry={onRetry}
          />
        ))}
      </div>
      {!following ? (
        <button
          className="kw-back-to-latest"
          type="button"
          onClick={() => {
            setFollowing(true);
            if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
          }}
        >
          回到最新消息
        </button>
      ) : null}
      <form className="kw-composer" onSubmit={onSubmit}>
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={onKeyDown}
          onCompositionStart={() => { composing.current = true; }}
          onCompositionEnd={() => { composing.current = false; }}
          placeholder="描述修改，或输入任务试跑…"
          rows={3}
          disabled={busy}
        />
        <div className="kw-composer-actions">
          <button type="button" onClick={() => void submit("update")} disabled={busy || !!activeTurn || !message.trim()}>修改</button>
          <button className="kw-primary-small" type="submit" disabled={busy || !!activeTurn || !message.trim()}>发送</button>
        </div>
      </form>
    </aside>
  );
}
