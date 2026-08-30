import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type {
  ConnectionProfile,
  TemplateKey,
  WorkspaceResource,
} from "../domain/types";
import type { KnowledgeSourceOption } from "../../../extensions/knowledge-source-contracts";

function AttachIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M8 12.5 13.8 6.7a3.2 3.2 0 0 1 4.5 4.5l-7.6 7.6a5 5 0 0 1-7.1-7.1l7.1-7.1" /></svg>;
}

function SendIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 14-7-5 14-2.4-5.6L5 12Z" /><path d="m11.6 13.4 3.1-3.1" /></svg>;
}

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>;
}

function ChevronIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 10 5 5 5-5" /></svg>;
}

function CheckIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /></svg>;
}

const TEMPLATE_OPTIONS: Array<{ key: TemplateKey; label: string }> = [
  { key: "generic", label: "Auto（自动推荐）" },
  { key: "semantic", label: "Semantic" },
  { key: "dashboard", label: "Dashboard" },
  { key: "sop", label: "SOP" },
];

export function SkillComposer({
  goal,
  onGoalChange,
  connections,
  resources,
  knowledgeSourceOptions,
  templateKey,
  onTemplateKeyChange,
  onOpenDataTools,
  onRemoveConnection,
  onRemoveResource,
  onRemoveKnowledgeSource,
  onSend,
  busy,
  error,
  autoFocus = false,
}: {
  goal: string;
  onGoalChange: (value: string) => void;
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  knowledgeSourceOptions: KnowledgeSourceOption[];
  templateKey: TemplateKey;
  onTemplateKeyChange: (value: TemplateKey) => void;
  onOpenDataTools: () => void;
  onRemoveConnection: (id: string) => void;
  onRemoveResource: (id: string) => void;
  onRemoveKnowledgeSource: (id: string) => void;
  onSend: () => void;
  busy: boolean;
  error?: string;
  autoFocus?: boolean;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const [templateOpen, setTemplateOpen] = useState(false);

  useEffect(() => {
    const node = textarea.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(Math.max(node.scrollHeight, 76), 200)}px`;
  }, [goal]);

  const removeConnection = (connection: ConnectionProfile) => {
    if (window.confirm("仅从当前 Skill 移除，不会删除我的连接中的实例。")) {
      onRemoveConnection(connection.connection_id);
    }
  };
  const removeResource = (resource: WorkspaceResource) => {
    if (window.confirm("仅从当前 Skill 移除，不会删除我的连接中的实例。")) {
      onRemoveResource(resource.resource_id);
    }
  };
  const removeKnowledgeSource = (option: KnowledgeSourceOption) => {
    if (window.confirm("仅从当前 Skill 移除，不会删除外部知识源配置或资源。")) {
      onRemoveKnowledgeSource(option.id);
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
    onSend();
  };

  return (
    <div className="kw-skill-composer">
      {(connections.length > 0 || resources.length > 0 || knowledgeSourceOptions.length > 0) ? (
        <div className="kw-composer-context" aria-label="当前数据与工具">
          {connections.map((connection) => (
            <span key={connection.connection_id}>
              <AttachIcon />
              {connection.display_name}
              <button type="button" aria-label={`移除 ${connection.display_name}`} onClick={() => removeConnection(connection)}>
                <CloseIcon />
              </button>
            </span>
          ))}
          {resources.map((resource) => (
            <span key={resource.resource_id}>
              <AttachIcon />
              {resource.display_name}
              <button type="button" aria-label={`移除 ${resource.display_name}`} onClick={() => removeResource(resource)}>
                <CloseIcon />
              </button>
            </span>
          ))}
          {knowledgeSourceOptions.map((option) => (
            <span key={option.id}>
              <AttachIcon />
              {option.displayName}
              <button type="button" aria-label={`移除 ${option.displayName}`} onClick={() => removeKnowledgeSource(option)}>
                <CloseIcon />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <textarea
        ref={textarea}
        value={goal}
        onChange={(event) => onGoalChange(event.target.value)}
        onKeyDown={keyDown}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }}
        placeholder="描述你希望 Agent 学会的业务工作…"
        aria-label="描述业务任务"
        rows={3}
        autoFocus={autoFocus}
        disabled={busy}
      />
      {error ? <div className="kw-composer-error" role="alert">{error}</div> : null}
      <div className="kw-skill-composer-footer">
        <button className="kw-add-context" type="button" onClick={onOpenDataTools}>
          <AttachIcon /> 添加数据与工具
        </button>
        <div className="kw-template-menu">
          <button
            type="button"
            className="kw-template-trigger"
            aria-haspopup="listbox"
            aria-expanded={templateOpen}
            onClick={() => setTemplateOpen((open) => !open)}
          >
            {TEMPLATE_OPTIONS.find((option) => option.key === templateKey)?.label}
            <ChevronIcon />
          </button>
          {templateOpen ? (
            <div className="kw-template-popover" role="listbox" aria-label="产物类型">
              {TEMPLATE_OPTIONS.map((option) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={templateKey === option.key}
                  key={option.key}
                  onClick={() => {
                    onTemplateKeyChange(option.key);
                    setTemplateOpen(false);
                  }}
                >
                  {option.label}
                  {templateKey === option.key ? <CheckIcon /> : null}
                </button>
              ))}
            </div>
          ) : null}
          <button
            type="button"
            className="kw-composer-send"
            aria-label="发送"
            onClick={onSend}
            disabled={busy || !goal.trim()}
          >
            <SendIcon />
          </button>
        </div>
      </div>
    </div>
  );
}
