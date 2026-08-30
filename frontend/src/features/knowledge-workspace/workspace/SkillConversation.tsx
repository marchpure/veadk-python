import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type UIEvent,
} from "react";
import { ConversationTurn } from "../assistant/ConversationTurn";
import type { ConversationTurnModel } from "../assistant/assistant-model";
import type {
  ConnectionProfile,
  WorkspaceResource,
} from "../domain/types";

function SendIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 14-7-5 14-2.4-5.6L5 12Z" /><path d="m11.6 13.4 3.1-3.1" /></svg>;
}

function MenuIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" /></svg>;
}

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>;
}

export function SkillConversation({
  title,
  turns,
  connections,
  resources,
  busy,
  focusInvocationId,
  onOpenInvocations,
  onOpenArtifacts,
  onOpenDataTools,
  onRemoveConnection,
  onRemoveResource,
  onSend,
  onRun,
  onCancel,
  onReconnect,
  onRetry,
}: {
  title: string;
  turns: ConversationTurnModel[];
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  busy: boolean;
  focusInvocationId?: string;
  onOpenInvocations: () => void;
  onOpenArtifacts: () => void;
  onOpenDataTools: () => void;
  onRemoveConnection: (id: string) => void;
  onRemoveResource: (id: string) => void;
  onSend: (message: string, intent: "update" | "run") => Promise<void>;
  onRun: (message: string) => Promise<void>;
  onCancel: () => Promise<void>;
  onReconnect: (turn: ConversationTurnModel) => void;
  onRetry: (turn: ConversationTurnModel) => void;
}) {
  const [message, setMessage] = useState("");
  const [following, setFollowing] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  const submitting = useRef(false);
  const activeTurn = [...turns].reverse().find((turn) => turn.status === "queued" || turn.status === "running");

  useEffect(() => {
    if (focusInvocationId) {
      document.querySelector(`[data-invocation-id="${CSS.escape(focusInvocationId)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (following && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [focusInvocationId, following, turns]);

  const submit = async () => {
    const value = message.trim();
    if (!value || busy || activeTurn || submitting.current) return;
    submitting.current = true;
    setMessage("");
    setFollowing(true);
    try {
      await onSend(value, "update");
    } finally {
      submitting.current = false;
    }
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== "Enter"
      || event.shiftKey
      || composing.current
      || event.nativeEvent.isComposing
      || event.nativeEvent.keyCode === 229
    ) return;
    event.preventDefault();
    void submit();
  };
  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const node = event.currentTarget;
    setFollowing(node.scrollHeight - node.scrollTop - node.clientHeight < 48);
  };

  return (
    <section className="kw-skill-conversation" aria-label="Skill 对话">
      <header>
        <button type="button" className="kw-workshop-mobile-control" onClick={onOpenInvocations} aria-label="打开会话列表"><MenuIcon /></button>
        <h1>{title}</h1>
        <div>
          {activeTurn ? <button type="button" onClick={() => void onCancel()}>停止</button> : null}
          <button type="button" className="kw-run-revision" onClick={() => void onRun(message.trim() || turns.at(-1)?.userMessage || title)} disabled={busy || !!activeTurn}>
            试跑 / 刷新
          </button>
          <button type="button" className="kw-workshop-mobile-control" onClick={onOpenArtifacts} aria-label="打开产物">产物</button>
        </div>
      </header>
      <div className="kw-skill-transcript" ref={scroller} onScroll={onScroll} aria-live="polite">
        <div className="kw-skill-transcript-column">
          {turns.map((turn) => (
            <ConversationTurn key={turn.invocationId} turn={turn} onReconnect={onReconnect} onRetry={onRetry} />
          ))}
          {!turns.length ? <div className="kw-chat-empty">继续描述修改，Agent 会更新当前 Skill。</div> : null}
        </div>
      </div>
      {!following ? <button type="button" className="kw-back-to-latest" onClick={() => {
        setFollowing(true);
        if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
      }}>回到最新消息</button> : null}
      <div className="kw-workshop-composer-wrap">
        <div className="kw-workshop-composer">
          {(connections.length || resources.length) ? (
            <div className="kw-workshop-context">
              {connections.map((item) => (
                <span key={item.connection_id}>
                  <button type="button" onClick={onOpenDataTools}>{item.display_name}</button>
                  <button type="button" aria-label={`移除 ${item.display_name}`} onClick={() => {
                    if (window.confirm("仅从当前 Skill 移除，不会删除我的连接中的实例。")) onRemoveConnection(item.connection_id);
                  }}><CloseIcon /></button>
                </span>
              ))}
              {resources.map((item) => (
                <span key={item.resource_id}>
                  <button type="button" onClick={onOpenDataTools}>{item.display_name}</button>
                  <button type="button" aria-label={`移除 ${item.display_name}`} onClick={() => {
                    if (window.confirm("仅从当前 Skill 移除，不会删除我的连接中的实例。")) onRemoveResource(item.resource_id);
                  }}><CloseIcon /></button>
                </span>
              ))}
            </div>
          ) : null}
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={keyDown}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={() => { composing.current = false; }}
            placeholder="继续描述你想修改的内容…"
            aria-label="修改当前 Skill"
            rows={3}
            disabled={busy}
          />
          <div className="kw-workshop-composer-actions">
            <button type="button" onClick={onOpenDataTools}>添加数据与工具</button>
            <button type="button" className="kw-composer-send" aria-label="发送修改" onClick={() => void submit()} disabled={busy || !!activeTurn || !message.trim()}>
              <SendIcon />
            </button>
          </div>
          <input type="hidden" value="update" readOnly data-intent="update" />
        </div>
      </div>
    </section>
  );
}
