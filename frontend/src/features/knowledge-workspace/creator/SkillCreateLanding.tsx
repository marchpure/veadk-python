import { useState } from "react";
import type { ReactNode } from "react";
import type {
  ConnectionProfile,
  TemplateKey,
  WorkspaceResource,
} from "../domain/types";
import type {
  KnowledgeSourceAction,
  KnowledgeSourceOption,
} from "../../../extensions/knowledge-source-contracts";
import { SkillComposer } from "./SkillComposer";

const SUGGESTIONS = ["分析华东区域异常", "生成蓝牙诊断 SOP", "制作门店巡检看板"];

function SkillIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 32 32">
      <rect x="6" y="7" width="20" height="18" rx="6" />
      <path d="M11 13h10M11 18h6M16 4v3M12 25v3M20 25v3" />
    </svg>
  );
}

export function SkillCreateLanding({
  goal,
  setGoal,
  connections,
  resources,
  knowledgeSourceActions,
  knowledgeSourceOptions,
  selectedConnectionIds,
  selectedResourceIds,
  selectedKnowledgeSourceOptionIds,
  templateKey,
  setTemplateKey,
  onOpenDataTools,
  onCreateConnection,
  onRemoveConnection,
  onRemoveResource,
  onRemoveKnowledgeSource,
  onCreate,
  busy,
  error,
  beforeSlot,
}: {
  goal: string;
  setGoal: (value: string) => void;
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  knowledgeSourceActions: KnowledgeSourceAction[];
  knowledgeSourceOptions: KnowledgeSourceOption[];
  selectedConnectionIds: string[];
  selectedResourceIds: string[];
  selectedKnowledgeSourceOptionIds: string[];
  templateKey: TemplateKey;
  setTemplateKey: (value: TemplateKey) => void;
  onOpenDataTools: () => void;
  onCreateConnection: () => void;
  onRemoveConnection: (id: string) => void;
  onRemoveResource: (id: string) => void;
  onRemoveKnowledgeSource: (id: string) => void;
  onCreate: () => void;
  busy: boolean;
  error?: string;
  beforeSlot?: ReactNode;
}) {
  const [contextRequired, setContextRequired] = useState(false);
  const selectedConnections = connections.filter((connection) => selectedConnectionIds.includes(connection.connection_id));
  const selectedResources = resources.filter((resource) => selectedResourceIds.includes(resource.resource_id));
  const selectedKnowledgeSources = knowledgeSourceOptions.filter((option) => selectedKnowledgeSourceOptionIds.includes(option.id));
  const send = () => {
    if (!selectedConnectionIds.length && !selectedResourceIds.length && !selectedKnowledgeSourceOptionIds.length) {
      setContextRequired(true);
      onOpenDataTools();
      return;
    }
    setContextRequired(false);
    onCreate();
  };

  return (
    <>
      {beforeSlot}
      <section className="kw-skill-create-landing">
        <div className="kw-skill-create-content">
          <div className="kw-skill-create-icon"><SkillIcon /></div>
          <h1>创建一个新技能</h1>
          <p>描述业务工作，选择数据和工具，由 Agent 生成可复用 Skill</p>
          <div className="kw-create-entry-cards" aria-label="新建入口">
            <button type="button" className="kw-create-entry-card" onClick={onCreateConnection}>
              <strong>创建连接</strong>
              <span>接入数据库、文件、API 或 MCP，继续使用现有 Connection catalog。</span>
            </button>
            {knowledgeSourceActions.map((action) => (
              <button
                type="button"
                className="kw-create-entry-card"
                key={action.id}
                onClick={action.run}
              >
                <strong>{action.label}</strong>
                <span>{action.description}</span>
              </button>
            ))}
          </div>
          <SkillComposer
            goal={goal}
            onGoalChange={setGoal}
            connections={selectedConnections}
            resources={selectedResources}
            knowledgeSourceOptions={selectedKnowledgeSources}
            templateKey={templateKey}
            onTemplateKeyChange={setTemplateKey}
            onOpenDataTools={onOpenDataTools}
            onRemoveConnection={onRemoveConnection}
            onRemoveResource={onRemoveResource}
            onRemoveKnowledgeSource={onRemoveKnowledgeSource}
            onSend={send}
            busy={busy}
            error={error}
            autoFocus
          />
          {contextRequired ? (
            <div className="kw-context-required" role="alert">请先选择至少一个可用的 Connection 或 Resource。</div>
          ) : null}
          {busy ? (
            <div className="kw-create-progress" role="status">
              <span className="kw-create-progress-user">{goal}</span>
              <span>正在创建 Skill Draft 并启动第一次生成…</span>
            </div>
          ) : null}
          <div className="kw-skill-suggestions" aria-label="任务建议">
            {SUGGESTIONS.map((suggestion) => (
              <button type="button" key={suggestion} onClick={() => setGoal(suggestion)}>{suggestion}</button>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
