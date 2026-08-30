import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type KeyboardEvent,
  type UIEvent,
} from "react";
import { ConversationTurn } from "../assistant/ConversationTurn";
import type { ConversationTurnModel } from "../assistant/assistant-model";
import type {
  AuthoringSession,
  ConnectionProfile,
  WorkspaceResource,
} from "../domain/types";

function SendIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 14-7-5 14-2.4-5.6L5 12Z" /><path d="m11.6 13.4 3.1-3.1" /></svg>;
}

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>;
}

function PlusIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>;
}

function RefreshIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M20 11a8 8 0 0 0-14.5-4.7L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.7L20 16M16 16h4v4" /></svg>;
}

function formatSessionUpdated(value?: string): string {
  if (!value) return "未同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未同步";
  return date.toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" });
}

const SESSION_STATUS_LABELS: Record<AuthoringSession["status"], string> = {
  idle: "空闲",
  running: "运行中",
  archived: "已归档",
};

export function SkillConversation({
  title,
  turns,
  connections,
  resources,
  sessions,
  currentSession,
  composerValue,
  busy,
  focusInvocationId,
  modeSelectorSlot,
  hasArtifacts,
  onOpenArtifacts,
  onOpenDataTools,
  onCreateSession,
  onSelectSession,
  onRefreshSession,
  onComposerDraftChange,
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
  sessions: AuthoringSession[];
  currentSession: AuthoringSession | null;
  composerValue: string;
  busy: boolean;
  focusInvocationId?: string;
  modeSelectorSlot?: ReactNode;
  hasArtifacts?: boolean;
  onOpenArtifacts?: () => void;
  onOpenDataTools: () => void;
  onCreateSession: () => Promise<void>;
  onSelectSession: (authoringSessionId: string) => void;
  onRefreshSession: () => Promise<void>;
  onComposerDraftChange: (value: string) => void;
  onRemoveConnection: (id: string) => void;
  onRemoveResource: (id: string) => void;
  onSend: (message: string, intent: "update" | "run") => Promise<void>;
  onRun: (message: string) => Promise<void>;
  onCancel: () => Promise<void>;
  onReconnect: (turn: ConversationTurnModel) => void;
  onRetry: (turn: ConversationTurnModel) => void;
}) {
  const message = composerValue;
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
    onComposerDraftChange("");
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
        <div className="kw-skill-title-block">
          <h1>{title}</h1>
          <div className="kw-session-toolbar">
            <label>
              <span>Session</span>
              <select
                value={currentSession?.authoring_session_id || ""}
                onChange={(event) => onSelectSession(event.target.value)}
                aria-label="选择作者会话"
                disabled={!sessions.length || busy}
              >
                {sessions.map((session) => (
                  <option key={session.authoring_session_id} value={session.authoring_session_id}>
                    {session.title} · {SESSION_STATUS_LABELS[session.status]} · {formatSessionUpdated(session.updated_at)}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="kw-session-icon-button" onClick={() => void onCreateSession()} disabled={busy} aria-label="新建会话">
              <PlusIcon />
            </button>
            <button type="button" className="kw-session-icon-button" onClick={() => void onRefreshSession()} disabled={!currentSession || busy} aria-label="刷新当前会话">
              <RefreshIcon />
            </button>
            {currentSession?.active_invocation_id ? <span className="kw-session-running">运行中</span> : null}
          </div>
        </div>
        <div className="kw-skill-header-actions">
          {modeSelectorSlot}
          {activeTurn ? <button type="button" onClick={() => void onCancel()}>停止</button> : null}
          <button type="button" className="kw-run-revision" onClick={() => void onRun(message.trim() || turns.at(-1)?.userMessage || title)} disabled={busy || !!activeTurn}>
            试跑 / 刷新
          </button>
          {hasArtifacts && onOpenArtifacts ? <button type="button" className="kw-workshop-mobile-control" onClick={onOpenArtifacts} aria-label="打开产物">产物</button> : null}
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
            onChange={(event) => onComposerDraftChange(event.target.value)}
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
