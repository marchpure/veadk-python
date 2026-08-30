import { useEffect, useMemo, useState } from "react";
import type {
  ConnectionProfile,
  WorkspaceResource,
} from "../domain/types";

const CONNECTION_STATUS: Record<ConnectionProfile["status"], string> = {
  draft: "草稿",
  validating: "验证中",
  ready: "可用",
  degraded: "需关注",
  error: "错误",
  revoked: "已撤销",
};

type Category = "全部" | "数据库" | "文件与表格" | "对象存储" | "API / MCP" | "办公与知识";
const CATEGORIES: Category[] = ["全部", "数据库", "文件与表格", "对象存储", "API / MCP", "办公与知识"];

function categoryFor(value: string): Category {
  const key = value.toLowerCase();
  if (/oracle|mysql|postgres|database|sql|doris|clickhouse/.test(key)) return "数据库";
  if (/file|sheet|csv|excel/.test(key)) return "文件与表格";
  if (/storage|s3|tos|oss/.test(key)) return "对象存储";
  if (/api|http|mcp|rest/.test(key)) return "API / MCP";
  return "办公与知识";
}

function SearchIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>;
}

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>;
}

function CheckIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /></svg>;
}

export function DataToolDrawer({
  open,
  connections,
  resources,
  selectedConnectionIds,
  selectedResourceIds,
  onConfirm,
  onClose,
  onConfigureConnection,
}: {
  open: boolean;
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  selectedConnectionIds: string[];
  selectedResourceIds: string[];
  onConfirm: (connectionIds: string[], resourceIds: string[]) => void;
  onClose: () => void;
  onConfigureConnection: (connection: ConnectionProfile) => void;
}) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<Category>("全部");
  const [connectionIds, setConnectionIds] = useState(selectedConnectionIds);
  const [resourceIds, setResourceIds] = useState(selectedResourceIds);

  useEffect(() => {
    if (!open) return;
    setConnectionIds(selectedConnectionIds);
    setResourceIds(selectedResourceIds);
  }, [open, selectedConnectionIds, selectedResourceIds]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const items = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return [
      ...connections.map((connection) => ({
        kind: "connection" as const,
        id: connection.connection_id,
        name: connection.display_name,
        type: connection.connector_key,
        scope: connection.scope,
        status: CONNECTION_STATUS[connection.status],
        category: categoryFor(connection.connector_key),
        ready: connection.status === "ready",
        connection,
      })),
      ...resources.map((resource) => ({
        kind: "resource" as const,
        id: resource.resource_id,
        name: resource.display_name,
        type: resource.kind,
        scope: resource.scope,
        status: resource.status,
        category: categoryFor(resource.kind),
        ready: resource.status === "verified",
        resource,
      })),
    ].filter((item) =>
      (category === "全部" || item.category === category)
      && (!normalizedSearch || `${item.name} ${item.type}`.toLowerCase().includes(normalizedSearch)),
    );
  }, [category, connections, resources, search]);

  if (!open) return null;
  const selectedCount = connectionIds.length + resourceIds.length;
  return (
    <div className="kw-drawer-layer" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="kw-data-tool-drawer" role="dialog" aria-modal="true" aria-label="添加数据与工具">
        <header>
          <h2>添加数据与工具</h2>
          <button type="button" aria-label="关闭" onClick={onClose}><CloseIcon /></button>
        </header>
        <div className="kw-data-tool-search">
          <SearchIcon />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索连接或资源" aria-label="搜索连接或资源" />
        </div>
        <div className="kw-data-tool-categories" role="tablist" aria-label="资源分类">
          {CATEGORIES.map((item) => (
            <button type="button" role="tab" aria-selected={category === item} key={item} onClick={() => setCategory(item)}>{item}</button>
          ))}
        </div>
        <div className="kw-data-tool-list">
          {items.map((item) => {
            const selected = item.kind === "connection"
              ? connectionIds.includes(item.id)
              : resourceIds.includes(item.id);
            return (
              <div className={`kw-data-tool-row${selected ? " is-selected" : ""}${item.ready ? "" : " is-disabled"}`} key={`${item.kind}:${item.id}`}>
                <button
                  type="button"
                  className="kw-data-tool-select"
                  disabled={!item.ready}
                  aria-pressed={selected}
                  onClick={() => {
                    if (item.kind === "connection") {
                      setConnectionIds((current) => selected ? current.filter((id) => id !== item.id) : [...current, item.id]);
                    } else {
                      setResourceIds((current) => selected ? current.filter((id) => id !== item.id) : [...current, item.id]);
                    }
                  }}
                >
                  <span className="kw-data-tool-check">{selected ? <CheckIcon /> : null}</span>
                  <span className="kw-data-tool-copy">
                    <strong>{item.name}</strong>
                    <small>{item.type} · {item.scope === "team" ? "团队" : "个人"}</small>
                  </span>
                  <span className={`kw-data-tool-status is-${item.ready ? "ready" : "unavailable"}`}>{item.status}</span>
                </button>
                {!item.ready && item.kind === "connection" ? (
                  <button type="button" className="kw-data-tool-configure" onClick={() => onConfigureConnection(item.connection)}>去配置</button>
                ) : null}
              </div>
            );
          })}
          {!items.length ? <div className="kw-data-tool-empty">没有找到符合条件的数据或工具</div> : null}
        </div>
        <footer>
          <span>已选 <strong>{selectedCount}</strong> 个</span>
          <div>
            <button type="button" onClick={onClose}>取消</button>
            <button type="button" className="kw-primary-small" onClick={() => onConfirm(connectionIds, resourceIds)}>确认选择</button>
          </div>
        </footer>
      </section>
    </div>
  );
}
