import { StrictMode, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import type { AgentRuntimeContext, ResourceReference } from "./contracts";
import { AgentConversation } from "./AgentConversation";
import "./harness.css";

type SkillKind = NonNullable<AgentRuntimeContext["requestedKind"]>;
type Scope = NonNullable<AgentRuntimeContext["scope"]>;

function queryValue(name: string): string {
  return new URLSearchParams(window.location.search).get(name)?.trim() ?? "";
}

function AgentRuntimeHarness() {
  const [requestedKind, setRequestedKind] = useState<SkillKind | "">(
    (queryValue("kind") as SkillKind) || "",
  );
  const [resourceKind, setResourceKind] = useState(
    queryValue("resourceKind") || "golden_asset",
  );
  const [objectId, setObjectId] = useState(queryValue("objectId"));
  const [revision, setRevision] = useState(queryValue("revision"));
  const [scope, setScope] = useState<Scope>(
    queryValue("scope") === "team" ? "team" : "personal",
  );
  const [currentSkillId, setCurrentSkillId] = useState(queryValue("skillId"));
  const [currentViewId, setCurrentViewId] = useState(queryValue("viewId"));
  const [currentComponentId, setCurrentComponentId] = useState(
    queryValue("componentId"),
  );
  const conversationId = queryValue("conversationId") || "agent-runtime-harness";
  const resourceRefs = useMemo<ResourceReference[]>(
    () =>
      objectId.trim() && revision.trim()
        ? [{
          kind: resourceKind.trim() || "golden_asset",
          objectId: objectId.trim(),
          revision: revision.trim(),
          scope,
        }]
        : [],
    [objectId, resourceKind, revision, scope],
  );
  const context = useMemo<AgentRuntimeContext>(
    () => ({
      conversationId,
      ...(requestedKind ? { requestedKind } : {}),
      scope,
      resourceRefs,
      fixedRevisions: resourceRefs.map((resource) => resource.revision),
      permissions: resourceRefs.length > 0 ? ["resource:read"] : [],
      ...(currentSkillId ? { currentSkillId } : {}),
      ...(currentViewId ? { currentViewId } : {}),
      ...(currentComponentId ? { currentComponentId } : {}),
    }),
    [
      currentComponentId,
      conversationId,
      currentSkillId,
      currentViewId,
      requestedKind,
      resourceRefs,
      scope,
    ],
  );

  return (
    <main className="runtime-harness">
      <aside className="runtime-harness__settings" aria-label="验收上下文">
        <div className="runtime-harness__intro">
          <h1>Agent Runtime 验收</h1>
          <p>
            直接连接真实 durable SSE 接口。问候无需资源；Skill 与工具链验收请填写已授权
            revision。
          </p>
        </div>
        <label>
          <span>请求类型</span>
          <select
            value={requestedKind}
            onChange={(event) =>
              setRequestedKind(event.target.value as SkillKind | "")}
          >
            <option value="">自动路由</option>
            <option value="knowledge">Knowledge Skill</option>
            <option value="semantic">Semantic Skill</option>
            <option value="analysis">Analysis Skill</option>
            <option value="graph_ontology">Graph Ontology Skill</option>
            <option value="monitoring">Monitoring Skill</option>
          </select>
        </label>
        <label>
          <span>资源类型</span>
          <input
            value={resourceKind}
            onChange={(event) => setResourceKind(event.target.value)}
            placeholder="golden_asset"
          />
        </label>
        <label>
          <span>资源 ID</span>
          <input
            value={objectId}
            onChange={(event) => setObjectId(event.target.value)}
            placeholder="可留空"
          />
        </label>
        <label>
          <span>固定 revision</span>
          <input
            value={revision}
            onChange={(event) => setRevision(event.target.value)}
            placeholder="可留空"
          />
        </label>
        <label>
          <span>作用域</span>
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value as Scope)}
          >
            <option value="personal">个人</option>
            <option value="team">团队</option>
          </select>
        </label>
        <label>
          <span>当前 Skill ID</span>
          <input
            value={currentSkillId}
            onChange={(event) => setCurrentSkillId(event.target.value)}
            placeholder="可选：用于修改当前 Skill"
          />
        </label>
        <label>
          <span>当前 ViewRevision ID</span>
          <input
            value={currentViewId}
            onChange={(event) => setCurrentViewId(event.target.value)}
            placeholder="可选：用于恢复当前视图"
          />
        </label>
        <label>
          <span>当前组件 ID</span>
          <input
            value={currentComponentId}
            onChange={(event) => setCurrentComponentId(event.target.value)}
            placeholder="kpi / chart / filter / sop-step"
          />
        </label>
        <p className="runtime-harness__note">
          当前上下文将在下一次发送时生效。凭证与连接配置仅由服务端管理。
        </p>
      </aside>
      <section className="runtime-harness__stage">
        <AgentConversation
          title="Agent 对话"
          context={context}
          storageKey={`knowledge-agent-runtime.harness.${conversationId}`}
        />
      </section>
    </main>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("Agent Runtime harness root is missing.");
createRoot(root).render(
  <StrictMode>
    <AgentRuntimeHarness />
  </StrictMode>,
);
