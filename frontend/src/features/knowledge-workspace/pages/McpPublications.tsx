import { useCallback, useEffect, useMemo, useState } from "react";
import {
  mcpPublicationApi,
  type McpActionPolicy,
  type McpPublicationView,
} from "../api/mcpPublications";
import type { ConnectionProfile, ConnectorDefinition } from "../domain/types";
import { Modal } from "../components/Modal";

const STEPS = ["选择数据", "设置权限", "选择使用者", "确认发布"];
const PROGRESS: Record<string, string> = {
  draft_saved: "准备权限",
  validated: "准备权限",
  runtime_token_created: "托管凭据",
  credential_managed: "创建 Gateway",
  gateway_created: "创建 Gateway",
  audience_bound: "验证访问",
  verifying: "验证访问",
  complete: "发布完成",
  failed: "发布失败",
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function audienceLabel(view: McpPublicationView): string {
  const current = view.activeRevision || view.revisions[0];
  const subjects = view.subjects.filter((item) => item.revision_id === current?.id);
  return subjects.map((item) => item.subject_ref).join("、") || "未配置";
}

function normalizedEndpoint(value?: string): string {
  const endpoint = value?.trim().replace(/\/+$/, "") || "";
  if (!endpoint) return "";
  return endpoint.endsWith("/mcp") ? endpoint : `${endpoint}/mcp`;
}

export function McpPublicationWizard({
  initialConnection,
  connections,
  connectors,
  onClose,
  onCreated,
  editPublication,
}: {
  initialConnection: ConnectionProfile;
  connections: ConnectionProfile[];
  connectors: ConnectorDefinition[];
  onClose: () => void;
  onCreated: (value: McpPublicationView) => void;
  editPublication?: McpPublicationView;
}) {
  const editRevision = editPublication?.activeRevision || editPublication?.revisions[0];
  const editClients = editPublication?.subjects
    .filter((item) => item.revision_id === editRevision?.id && item.subject_type === "application")
    .map((item) => item.subject_ref) || [];
  const [step, setStep] = useState(0);
  const [name, setName] = useState(editPublication?.publication.name || `${initialConnection.display_name} MCP`);
  const [connectionIds, setConnectionIds] = useState(editRevision?.connection_scope || [initialConnection.connection_id]);
  const [policy, setPolicy] = useState<McpActionPolicy["preset"]>(editRevision?.action_policy_source.preset || "read_only");
  const [customActions, setCustomActions] = useState<string[]>(editRevision?.action_policy_source.actionIds || []);
  const [clientText, setClientText] = useState(editClients.join("\n"));
  const [advanced, setAdvanced] = useState(false);
  const [confirmWrite, setConfirmWrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const connectorByKey = useMemo(
    () => new Map(connectors.map((item) => [item.connector_key, item])),
    [connectors],
  );
  const initialEndpoint = normalizedEndpoint(
    initialConnection.mcp_endpoint,
  );
  const selected = connections.filter((item) => connectionIds.includes(item.connection_id));
  const actionIds = Array.from(new Set(selected.flatMap(
    (item) => connectorByKey.get(item.connector_key)?.action_ids || [],
  )));
  const readActions = actionIds.filter((item) =>
    /(^|[._:/-])(get|list|read|search|query|describe|show|fetch|inspect|preview)($|[._:/-])/i.test(item),
  );
  const resolved = policy === "read_only" ? readActions : policy === "custom" ? customActions : actionIds;
  const clients = clientText.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean);
  const eligible = connections.filter((item) => {
    if (item.status !== "ready" || item.connection_id === initialConnection.connection_id) {
      return false;
    }
    const endpoint = normalizedEndpoint(item.mcp_endpoint);
    return Boolean(initialEndpoint && endpoint && endpoint === initialEndpoint);
  });
  const valid = [
    connectionIds.length > 0 &&
      Boolean(initialEndpoint) &&
      selected.every((item) => item.status === "ready" && normalizedEndpoint(item.mcp_endpoint) === initialEndpoint),
    resolved.length > 0,
    clients.length > 0,
    policy === "read_only" || confirmWrite,
  ][step];

  return (
    <Modal title="发布为 MCP" onClose={onClose}>
      <div className="kw-mcp-wizard">
        <ol className="kw-mcp-steps">
          {STEPS.map((label, index) => (
            <li key={label} className={index === step ? "is-current" : index < step ? "is-done" : ""}>
              <span>{index + 1}</span>{label}
            </li>
          ))}
        </ol>
        {step === 0 ? (
          <section>
            <h3>选择数据</h3>
            <label className="kw-mcp-choice">
              <input type="checkbox" checked readOnly />
              <span><strong>{initialConnection.display_name}</strong><small>{initialConnection.connector_key} · {initialConnection.status}</small></span>
            </label>
            <button type="button" className="kw-link-button" onClick={() => setAdvanced(!advanced)}>添加更多连接（高级）</button>
            {advanced ? eligible.map((item) => (
              <label className="kw-mcp-choice" key={item.connection_id}>
                <input
                  type="checkbox"
                  checked={connectionIds.includes(item.connection_id)}
                  onChange={(event) => setConnectionIds((current) =>
                    event.target.checked ? [...current, item.connection_id] : current.filter((id) => id !== item.connection_id),
                  )}
                />
                <span><strong>{item.display_name}</strong><small>{item.connector_key} · Endpoint 与当前连接一致</small></span>
              </label>
            )) : null}
          </section>
        ) : null}
        {step === 1 ? (
          <section>
            <h3>设置权限</h3>
            <div className="kw-mcp-policy-grid">
              {([
                ["read_only", "只读", "仅授权可明确识别的查询 Action"],
                ["read_write", "可读写", "授权当前连接公布的全部 Action"],
                ["custom", "自定义", "逐项选择 Action"],
              ] as const).map(([value, label, description]) => (
                <button type="button" className={policy === value ? "is-selected" : ""} onClick={() => setPolicy(value)} key={value}>
                  <strong>{label}</strong><small>{description}</small>
                </button>
              ))}
            </div>
            <div className="kw-mcp-actions">
              {actionIds.map((action) => {
                const allowed = policy === "read_write" || (policy === "read_only" && readActions.includes(action)) || customActions.includes(action);
                return (
                  <label key={action}>
                    {policy === "custom" ? <input type="checkbox" checked={allowed} onChange={(event) => setCustomActions((current) => event.target.checked ? [...current, action] : current.filter((item) => item !== action))} /> : null}
                    <code>{action}</code><span>{allowed ? "允许" : "默认不授权"}</span>
                  </label>
                );
              })}
            </div>
          </section>
        ) : null}
        {step === 2 ? (
          <section>
            <h3>选择使用者</h3>
            <div className="kw-state-card">
              <strong>应用客户端授权</strong>
              <span>Gateway 会校验 Access Token，并只允许这里列出的客户端。</span>
            </div>
            <label className="kw-mcp-field">允许的应用客户端
              <textarea value={clientText} onChange={(event) => setClientText(event.target.value)} placeholder="输入 Identity Client ID，多个可用逗号或换行分隔" />
            </label>
            <div className="kw-mcp-disabled">
              <strong>用户与用户组</strong>
              <span>当前环境未配置可执行的 Publication Access Broker，因此不可选择。</span>
            </div>
          </section>
        ) : null}
        {step === 3 ? (
          <section>
            <h3>确认发布</h3>
            <label className="kw-mcp-field">发布名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <p className="kw-mcp-summary">{clients.join("、")} 可以对 {selected.map((item) => item.display_name).join("、")} 执行 {resolved.length} 个{policy === "read_only" ? "只读" : "已选择"}操作。</p>
            {policy !== "read_only" ? <label className="kw-mcp-confirm"><input type="checkbox" checked={confirmWrite} onChange={(event) => setConfirmWrite(event.target.checked)} /> 我确认此发布包含写入能力</label> : null}
          </section>
        ) : null}
        {error ? <div className="kw-form-error" role="alert">{error}</div> : null}
        <footer className="kw-modal-actions">
          {step > 0 ? <button type="button" onClick={() => setStep(step - 1)}>上一步</button> : null}
          {step < 3 ? <button type="button" className="kw-primary-small" disabled={!valid} onClick={() => setStep(step + 1)}>下一步</button> : (
            <button
              type="button"
              className="kw-primary-small"
              disabled={!valid || !name.trim() || busy}
              onClick={async () => {
                setBusy(true); setError("");
                try {
                  const input = {
                    connectionIds,
                    actionPolicy: { preset: policy, ...(policy === "custom" ? { actionIds: customActions } : {}) },
                    audience: { type: "applications" as const, clientIds: clients },
                  };
                  const value = editPublication
                    ? await mcpPublicationApi.revise(editPublication.publication.id, input)
                    : await mcpPublicationApi.create({ name: name.trim(), ...input });
                  onCreated(value);
                } catch (cause) { setError(errorText(cause)); }
                finally { setBusy(false); }
              }}
            >{busy ? "发布中…" : editPublication ? "确认修改" : "确认发布"}</button>
          )}
        </footer>
      </div>
    </Modal>
  );
}

export function McpPublicationPage({
  publicationId,
  connections,
  connectors,
  onRefreshConnections,
  onSelect,
}: {
  publicationId?: string;
  connections: ConnectionProfile[];
  connectors: ConnectorDefinition[];
  onRefreshConnections: () => Promise<void>;
  onSelect: (id: string) => void;
}) {
  const [items, setItems] = useState<McpPublicationView[]>([]);
  const [selected, setSelected] = useState<McpPublicationView | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [capabilities, setCapabilities] = useState<McpPublicationView["capabilities"]>({
    audienceTypes: ["applications"],
  });
  const load = useCallback(async () => {
    try {
      const [list, availableCapabilities] = await Promise.all([
        mcpPublicationApi.list(),
        mcpPublicationApi.capabilities(),
      ]);
      setItems(list);
      setCapabilities(availableCapabilities);
      const target = publicationId ? list.find((item) => item.publication.id === publicationId) : null;
      setSelected(target || null);
      setError("");
    } catch (cause) { setError(errorText(cause)); }
  }, [publicationId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const state = selected?.publication.status;
    if (!state || !["provisioning", "verifying", "retrying", "updating", "disabling"].includes(state)) return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [load, selected?.publication.status]);
  const act = async (kind: "retry" | "verify" | "rotate" | "disable") => {
    if (!selected) return;
    setBusy(kind); setError("");
    try {
      const value = await mcpPublicationApi[kind](selected.publication.id);
      setSelected(value); await load();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(""); }
  };
  if (!selected) return (
    <section className="kw-detail kw-mcp-page">
      <div className="kw-detail-heading">
        <div><h1>MCP 发布</h1><p>面向应用客户端发布可审计的 Connection 与 Action 权限。</p></div>
        <div className="kw-detail-actions">
          {capabilities.connectionConsoleUrl ? <a className="kw-primary-small" href={capabilities.connectionConsoleUrl} target="_blank" rel="noreferrer">创建/管理连接</a> : null}
          <button type="button" onClick={() => void onRefreshConnections()}>刷新连接</button>
        </div>
      </div>
      <div className="kw-state-card">
        <strong>{connections.length ? "已连接" : "Connection Service 暂无可发布连接"}</strong>
        <span>{connections.length ? `已加载 ${connections.length} 个连接。` : "请先在连接管理中创建并验证连接，然后返回此处刷新连接。"}</span>
      </div>
      {error ? <div className="kw-form-error">{error}</div> : null}
      <div className="kw-mcp-list">
        {items.length ? items.map((item) => (
          <button type="button" key={item.publication.id} onClick={() => onSelect(item.publication.id)}>
            <span><strong>{item.publication.name}</strong><small>{item.activeRevision?.connection_scope.length || item.revisions[0]?.connection_scope.length || 0} 个连接 · {audienceLabel(item)}</small></span>
            <span className={`kw-pill is-${item.publication.status}`}>{item.publication.status}</span>
          </button>
        )) : <div className="kw-state-card">暂无 MCP 发布。请从 Connection 详情页开始。</div>}
      </div>
    </section>
  );
  const revision = selected.activeRevision || selected.revisions[0];
  const editConnection = connections.find((item) => item.connection_id === revision?.connection_scope[0]);
  if (editing && editConnection) {
    return (
      <McpPublicationWizard
        initialConnection={editConnection}
        connections={connections}
        connectors={connectors}
        editPublication={selected}
        onClose={() => setEditing(false)}
        onCreated={(value) => { setEditing(false); setSelected(value); void load(); }}
      />
    );
  }
  const operation = selected.operations[0];
  return (
    <section className="kw-detail kw-mcp-page">
      <button type="button" className="kw-detail-back" onClick={() => onSelect("")}>返回发布列表</button>
      <div className="kw-detail-heading">
        <div><h1>{selected.publication.name}</h1><p>Revision v{revision?.version} · {revision?.action_policy_source.preset}</p></div>
        <span className={`kw-pill is-${selected.publication.status}`}>{selected.publication.status}</span>
      </div>
      {error ? <div className="kw-form-error">{error}</div> : null}
      {operation && selected.publication.status !== "active" ? (
        <div className="kw-mcp-progress">
          <strong>{PROGRESS[operation.stage] || operation.stage}</strong>
          <span>第 {operation.attempt} 次尝试</span>
          {operation.last_error?.message ? <p>{operation.last_error.message}</p> : null}
        </div>
      ) : null}
      <div className="kw-detail-card">
        <h2>MCP 调用信息</h2>
        <code className="kw-mcp-endpoint">{revision?.gateway_endpoint || "Gateway 尚未就绪"}</code>
        <p>使用被允许应用客户端的短期 Access Token 调用；后台 API Key 不会返回浏览器。</p>
      </div>
      <div className="kw-detail-card">
        <h2>授权范围</h2>
        <p>Connection：{revision?.connection_scope.map((id) => connections.find((item) => item.connection_id === id)?.display_name || id).join("、")}</p>
        <div className="kw-mcp-actions">{revision?.resolved_action_scope.map((action) => <label key={action}><code>{action}</code><span>允许</span></label>)}</div>
        <p>应用客户端：{audienceLabel(selected)}</p>
      </div>
      <div className="kw-detail-actions">
        {selected.publication.status === "failed" ? <button type="button" disabled={Boolean(busy)} onClick={() => void act("retry")}>重试</button> : null}
        {selected.publication.status === "active" ? <>
          <button type="button" disabled={Boolean(busy)} onClick={() => void act("verify")}>验证</button>
          <button type="button" disabled={Boolean(busy) || !editConnection} onClick={() => setEditing(true)}>修改</button>
          <button type="button" disabled={Boolean(busy)} onClick={() => void act("rotate")}>轮换凭据</button>
          <button type="button" disabled={Boolean(busy)} onClick={() => void act("disable")}>停用</button>
        </> : null}
      </div>
      <div className="kw-detail-card"><h2>Revision 历史</h2>{selected.revisions.map((item) => <p key={item.id}>v{item.version} · {item.state} · {new Date(item.created_at).toLocaleString()}</p>)}</div>
      <div className="kw-detail-card"><h2>审计事件</h2>{selected.auditEvents.map((item) => <p key={item.id}>{item.event_type} · {item.actor} · {new Date(item.created_at).toLocaleString()}</p>)}</div>
      <details className="kw-mcp-diagnostics"><summary>管理员诊断信息</summary><pre>{JSON.stringify({ publicationId: selected.publication.id, revisionId: revision?.id }, null, 2)}</pre></details>
    </section>
  );
}

export function ConnectionPublications({
  connection,
  connections,
  connectors,
  onOpenPublication,
}: {
  connection: ConnectionProfile;
  connections: ConnectionProfile[];
  connectors: ConnectorDefinition[];
  onOpenPublication: (id: string) => void;
}) {
  const [wizard, setWizard] = useState(false);
  const [items, setItems] = useState<McpPublicationView[]>([]);
  useEffect(() => {
    void mcpPublicationApi.list().then((list) => setItems(list)).catch(() => setItems([]));
  }, []);
  const related = items.filter((item) =>
    item.revisions.some((revision) => revision.connection_scope.includes(connection.connection_id)),
  );
  return (
    <>
      <div className="kw-detail-card">
        <div className="kw-mcp-card-heading"><div><h2>已有发布</h2><p>发布由系统托管凭据并执行 Audience 校验。</p></div>
          <button type="button" className="kw-primary-small" disabled={connection.status !== "ready"} onClick={() => setWizard(true)}>发布为 MCP</button>
        </div>
        {related.length ? related.map((item) => <button className="kw-mcp-related" type="button" key={item.publication.id} onClick={() => onOpenPublication(item.publication.id)}><span>{item.publication.name}</span><span>{item.publication.status}</span></button>) : <p>此 Connection 暂无发布。</p>}
      </div>
      <details className="kw-detail-card"><summary>开发者访问</summary><p>手工 Runtime Token 仅用于高级调试，不参与 MCP 发布主流程。</p></details>
      {wizard ? <McpPublicationWizard initialConnection={connection} connections={connections} connectors={connectors} onClose={() => setWizard(false)} onCreated={(value) => { setWizard(false); onOpenPublication(value.publication.id); }} /> : null}
    </>
  );
}
